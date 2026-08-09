import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.modules.assistant import service
from app.modules.assistant.tools import TOOLS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assistant", tags=["Assistant"])


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
    return {
        "configured": service.is_configured(),
        "model": service.settings.ASSISTANT_MODEL if service.is_configured() else None,
        "tools": [{"name": t["name"], "description": t["description"]} for t in TOOLS],
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

    async def events():
        if not service.is_configured():
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

        client = service.build_client()
        try:
            async for event in service.converse(
                client=client,
                db=db,
                company_id=company_id,
                question=body.question,
                history=body.history,
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
