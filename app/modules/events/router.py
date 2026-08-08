import asyncio
import json
import logging
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.events.schemas import OutboxHealth, PaginatedEventResponse
from app.modules.events.service import EventService
from app.modules.events.stream import STREAM_KEY, decode, redis_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["Events"])

# How long to block on Redis before giving up and looping. The loop is what
# notices the client has disconnected, so this also bounds how long a dead
# connection stays open.
BLOCK_MS = 15_000
# Sent when a poll finds nothing. Without it an idle stream is indistinguishable
# from a broken one, and proxies close connections that go quiet.
KEEPALIVE = ": keepalive\n\n"


@router.get("/", response_model=PaginatedEventResponse)
def list_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None, description="Exact event type match"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Recent domain events, newest first.

    The history half of the event stream page: it loads this once so the page is
    not empty, then holds `/stream` open for everything after.
    """
    service = EventService(db)
    events, total = service.list_events(
        company_id=UUID(current_user["company_id"]),
        skip=skip,
        limit=limit,
        event_type=event_type,
    )
    return {"total": total, "skip": skip, "limit": limit, "data": events}


@router.get("/health", response_model=OutboxHealth)
def outbox_health(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Relay lag: how many events are waiting and how old the oldest one is."""
    return EventService(db).health(company_id=UUID(current_user["company_id"]))


@router.get("/stream")
async def stream_events(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Server-sent events: every new event for the caller's company, as it lands.

    Async on purpose. A streaming endpoint holds its connection open for as long
    as the tab is; written as a normal `def`, FastAPI would run it in the
    threadpool and each viewer would occupy one of a few dozen worker threads
    doing nothing but waiting. An async generator waiting on Redis costs a
    coroutine.

    The database session is released before streaming begins. `get_current_user`
    validates against Postgres, and holding that session for the life of the
    connection would exhaust the pool with a handful of open tabs. The
    consequence is honest and worth stating: a token revoked mid-stream keeps
    the existing connection alive until it drops. Revocation takes effect on the
    next connect, not instantly.

    Plain XREAD, not a consumer group: every viewer wants every event. Consumer
    groups divide work between workers, which is the opposite of what a live
    view needs -- with two tabs open, each would see half the events.
    """
    company_id = current_user["company_id"]

    async def publish():
        client = aioredis.from_url(redis_url())
        # "$" means "only what arrives after this moment". History comes from
        # the paged endpoint above, so starting at 0 would replay the entire
        # retained stream into a page that already has it.
        last_id = "$"
        try:
            while True:
                # Checked every loop rather than relying on the generator being
                # closed: a browser that goes away mid-block leaves this task
                # running until something notices.
                if await request.is_disconnected():
                    break

                response = await client.xread(
                    {STREAM_KEY: last_id}, count=50, block=BLOCK_MS
                )
                if not response:
                    yield KEEPALIVE
                    continue

                for _stream, entries in response:
                    for entry_id, fields in entries:
                        last_id = entry_id
                        event = decode(fields)

                        # The stream is shared by every tenant, so this filter
                        # is the isolation boundary. Dropping it would stream
                        # one company's trading activity to another's browser.
                        if event.get("company_id") != company_id:
                            continue

                        yield f"id: {event['sequence']}\n"
                        yield f"event: {event['event_type']}\n"
                        yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Event stream failed for company %s", company_id)
        finally:
            await client.aclose()

    return StreamingResponse(
        publish(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx buffers proxied responses by default, which for SSE means
            # the browser receives nothing until the buffer fills. It never
            # fills, so the page looks broken in production and fine locally.
            "X-Accel-Buffering": "no",
        },
    )
