import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import OptiStockException, ResourceNotFoundError
from app.core.rate_limit import limiter
from app.modules.assistant import service
from app.modules.assistant.actions import ActionService
from app.modules.assistant.redaction import describe_mode
from app.modules.assistant.runtime import get_runtime
from app.modules.assistant.tools import TOOLS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assistant", tags=["Assistant"])

#: Deliberately the same roles that POST /purchase-orders requires. An assistant
#: suggestion must not become a way around the permission governing the same
#: action taken by hand.
APPROVER_ROLES = {"admin", "supply_chain"}


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # Prior turns, so a follow-up ("and the other warehouse?") has something to
    # refer to. Capped because the client controls this field and an unbounded
    # history is an unbounded bill.
    history: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=20)


@router.get("/status")
def assistant_status(current_user: dict = Depends(get_current_user)):
    """Whether the assistant is usable, and what it can reach.

    The tool list is published deliberately. An assistant whose scope is
    invisible gets asked questions it cannot answer, and every one of those
    reads as a failure rather than as a boundary.
    """
    runtime = get_runtime()
    return {
        "configured": runtime.is_configured(),
        "provider": runtime.name,
        "model": runtime.model if runtime.is_configured() else None,
        "tools": [{"name": t["name"], "description": t["description"]} for t in TOOLS],
        # Published for the same reason as the tool list: a privacy boundary
        # nobody can see is a privacy boundary nobody trusts.
        "data_mode": describe_mode(),
        "max_tool_calls": service.settings.MAX_TOOL_CALLS,
    }


@router.post("/ask")
# Each question can trigger several model calls, so this is the one endpoint
# where a stuck loop or a bored user costs real money. Limited per address.
@limiter.limit("20/minute")
async def ask(
    request: Request,
    body: AskRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Answer a question about this company's data, streaming as it goes.

    The tenant is taken from the verified token here and passed down to every
    tool. It is never read from the request body, so no phrasing of a question
    can reach another company's rows.
    """
    company_id = UUID(current_user["company_id"])

    runtime = get_runtime()

    async def events():
        if not runtime.is_configured():
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        "The assistant isn't configured on this server. Set "
                        "GEMINI_API_KEY to enable it."
                    ),
                }
            )
            return

        try:
            async for event in service.converse(
                runtime=runtime,
                db=db,
                company_id=company_id,
                question=body.question,
                history=body.history,
                user_id=UUID(current_user["id"]),
            ):
                yield _sse(event)
        except Exception:
            logger.exception("Assistant stream failed")
            yield _sse(
                {"type": "error", "message": "The assistant stopped unexpectedly."}
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx buffers proxied responses by default, which for SSE means
            # the browser sees nothing until the buffer fills. It never does.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Proposed actions
#
# The half of the write path that a human drives. The assistant can reach the
# POST /ask endpoint above and nothing else; these three routes are the only
# way a proposal becomes a purchase order, and every one of them requires a
# session belonging to a real person.
# ---------------------------------------------------------------------------
class DecisionRequest(BaseModel):
    #: Lets the approver change the quantity before agreeing. The proposal keeps
    #: what the model asked for; the audit log ends up holding both.
    quantity: Optional[int] = Field(default=None, gt=0, le=10_000)
    reason: str = Field(default="", max_length=500)


#: Domain errors that are ordinary outcomes rather than faults, mapped to the
#: status that says so. Without this every one of them surfaced as a 500 --
#: including "you already approved that", which is what a double-click produces
#: and which the screen then reported as a server failure.
_STATUS_FOR = {
    "NOT_FOUND": 404,
    "ALREADY_DECIDED": 409,
    "PROPOSAL_EXPIRED": 409,
    "INVALID_QUANTITY": 400,
}


def _decide(operation):
    """Run one decision, translating domain errors the way this codebase does.

    A proposal id is a UUID a client supplies, and `ActionService.get` filters
    on company_id rather than checking it afterwards -- so another tenant's id
    arrives here as NOT_FOUND. Answering 404 is deliberate: a 403 would confirm
    the id exists, which is a small leak but a free one to avoid.
    """
    try:
        return operation()
    except ResourceNotFoundError as error:
        raise HTTPException(status_code=404, detail=error.message)
    except OptiStockException as error:
        raise HTTPException(
            status_code=_STATUS_FOR.get(error.code, 400), detail=error.message
        )


def _as_json(action) -> Dict[str, Any]:
    return {
        "id": str(action.id),
        "action_type": action.action_type,
        "status": action.status,
        "proposed": action.proposed_payload,
        "executed": action.executed_payload,
        "rationale": action.rationale,
        "source_question": action.source_question,
        "model": action.proposed_by_model,
        "proposed_at": action.proposed_at,
        "expires_at": action.expires_at,
        "decided_at": action.decided_at,
        "result_id": str(action.result_id) if action.result_id else None,
        "error": action.error,
        "is_actionable": action.is_actionable,
        # Computed here rather than in the browser so the screen cannot disagree
        # with the audit log about whether a human amended the machine.
        "amended": bool(
            action.executed_payload
            and action.executed_payload.get("quantity")
            != action.proposed_payload.get("quantity")
        ),
    }


@router.get("/actions")
def list_actions(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Proposals for this company, newest first."""
    actions = ActionService(db).list_actions(
        UUID(current_user["company_id"]), status=status
    )
    return {"actions": [_as_json(a) for a in actions]}


@router.post("/actions/{action_id}/approve")
def approve_action(
    action_id: UUID,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Execute a proposal, on the authority of the person calling this.

    Restricted to the roles that can create a purchase order by hand. An
    assistant suggestion must not become a way around the permission that
    governs the same action taken deliberately.
    """
    if current_user["role"] not in APPROVER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Your role cannot approve purchase orders.",
        )

    action = _decide(
        lambda: ActionService(db).approve(
            company_id=UUID(current_user["company_id"]),
            action_id=action_id,
            user_id=UUID(current_user["id"]),
            overrides={"quantity": body.quantity} if body.quantity else None,
        )
    )
    db.commit()
    db.refresh(action)
    return _as_json(action)


@router.post("/actions/{action_id}/reject")
def reject_action(
    action_id: UUID,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Decline a proposal, and keep the record of having declined it."""
    action = _decide(
        lambda: ActionService(db).reject(
            company_id=UUID(current_user["company_id"]),
            action_id=action_id,
            user_id=UUID(current_user["id"]),
            reason=body.reason,
        )
    )
    db.commit()
    db.refresh(action)
    return _as_json(action)
