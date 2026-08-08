"""The consumer side: workers that react to events.

Run it as its own process:

    python -m app.workers.consumers

This uses a Redis **consumer group**, which is the opposite of what the SSE
endpoint does and for the opposite reason. A group divides messages between its
members, so with three replicas each event is handled once in total -- correct
for work like raising an alert, where handling something twice means sending it
twice. The live view wants fan-out instead, so it plain-reads the stream.

Three properties a group gives that a plain read cannot:

*   **Offsets are server-side.** A worker that restarts resumes where the group
    left off rather than from the beginning or from now.
*   **Delivery is tracked.** A message stays pending until acknowledged, so a
    worker that dies mid-handler does not silently drop it.
*   **Pending work can be reclaimed.** `XAUTOCLAIM` hands a dead worker's
    messages to a live one after a timeout, which is what stops a crash from
    stranding events forever.

Handlers must be idempotent regardless. Delivery is at-least-once end to end --
the relay can republish, and a handler can succeed and then fail to ack -- so
"has this already been done" is the handler's problem to answer, not the
framework's to prevent.
"""

import logging
import os
import signal
import socket
import time
from typing import Callable, Dict, List

import redis
from redis.exceptions import ResponseError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  — completes the ORM registry for standalone runs
from app.core.database import SessionLocal
from app.modules.events.stream import (
    CONSUMER_GROUP,
    STREAM_KEY,
    decode,
    redis_url,
)

logger = logging.getLogger(__name__)

Handler = Callable[[Session, dict], None]

# event_type -> handlers. A list, because two unrelated things may care about
# one event and neither should have to know about the other.
_REGISTRY: Dict[str, List[Handler]] = {}

BLOCK_MS = 5_000
BATCH = 20
# How long a message may sit unacknowledged before another worker may take it.
# Longer than any handler should run; short enough that a crash is not a
# half-hour outage for that event.
CLAIM_IDLE_MS = 60_000


def on(event_type: str):
    """Register a handler for an event type.

    A decorator so a module declares what it reacts to next to the code that
    reacts, rather than in a wiring file that drifts out of date.
    """

    def register(fn: Handler) -> Handler:
        _REGISTRY.setdefault(event_type, []).append(fn)
        return fn

    return register


def registered_types() -> List[str]:
    return sorted(_REGISTRY)


def dispatch(db: Session, event: dict) -> int:
    """Run every handler registered for this event. Returns how many ran.

    A plain function so tests can hand it a decoded event and a session without
    a broker, a group or a loop. `Consumer` below is only the plumbing that
    feeds it.

    One handler raising does not stop the others: they are independent
    reactions, and letting a failing alert rule suppress an unrelated
    projection would couple them through nothing but execution order.
    """
    handlers = _REGISTRY.get(event.get("event_type", ""), [])
    ran = 0
    for handler in handlers:
        try:
            handler(db, event)
            ran += 1
        except Exception:
            logger.exception(
                "Handler %s failed for event %s",
                getattr(handler, "__name__", handler),
                event.get("event_id"),
            )
    return ran


class Consumer:
    def __init__(self, client: redis.Redis | None = None, session_factory=SessionLocal):
        self.redis = client or redis.Redis.from_url(redis_url())
        self.session_factory = session_factory
        # Identifies this worker inside the group. Host and pid so that two
        # replicas on one machine do not claim each other's pending messages.
        self.name = f"{socket.gethostname()}-{os.getpid()}"
        self._stopping = False

    def stop(self, *_args) -> None:
        logger.info("Consumer stopping after current batch.")
        self._stopping = True

    def ensure_group(self) -> None:
        """Create the group, tolerating the case where it already exists.

        `mkstream=True` creates the stream too. Without it a worker started
        before the first event ever published fails outright, which makes
        startup order matter -- and startup order is exactly the kind of thing
        that works locally and breaks in a deploy.
        """
        try:
            self.redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
            logger.info("Created consumer group %s.", CONSUMER_GROUP)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def _handle(self, entries) -> int:
        handled = 0
        for entry_id, fields in entries:
            event = decode(fields)
            db = self.session_factory()
            try:
                dispatch(db, event)
                db.commit()
                # Acknowledged only after the transaction commits. Acking first
                # would drop the message on a database failure; acking after
                # means a crash in between redelivers it, which the handlers
                # are built to tolerate.
                self.redis.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)
                handled += 1
            except Exception:
                db.rollback()
                logger.exception("Message %s failed; leaving it pending.", entry_id)
            finally:
                db.close()
        return handled

    def reclaim_stalled(self) -> int:
        """Take over messages a dead worker never acknowledged."""
        try:
            _cursor, entries, _deleted = self.redis.xautoclaim(
                STREAM_KEY,
                CONSUMER_GROUP,
                self.name,
                min_idle_time=CLAIM_IDLE_MS,
                count=BATCH,
            )
        except ResponseError:
            return 0
        if not entries:
            return 0
        logger.info("Reclaimed %d stalled messages.", len(entries))
        return self._handle(entries)

    def consume_once(self) -> int:
        """Read and handle one batch of new messages."""
        response = self.redis.xreadgroup(
            CONSUMER_GROUP,
            self.name,
            # ">" means "messages never delivered to anyone in this group".
            {STREAM_KEY: ">"},
            count=BATCH,
            block=BLOCK_MS,
        )
        if not response:
            return 0

        handled = 0
        for _stream, entries in response:
            handled += self._handle(entries)
        return handled

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        self.ensure_group()
        logger.info(
            "Consumer %s started. Reacting to: %s",
            self.name,
            ", ".join(registered_types()) or "nothing registered",
        )

        while not self._stopping:
            try:
                self.reclaim_stalled()
                self.consume_once()
            except Exception:
                logger.exception("Consumer loop failed; retrying.")
                time.sleep(2)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Importing the handler modules is what populates the registry. Without
    # this the consumer starts cleanly, reads the stream and reacts to nothing.
    import app.modules.alerts.handlers  # noqa: F401

    Consumer().run()


if __name__ == "__main__":
    # Deliberately re-entered through the canonical module rather than calling
    # main() directly.
    #
    # `python -m app.workers.consumers` runs this file as the module `__main__`.
    # When a handler then does `from app.workers.consumers import on`, Python
    # imports this file a SECOND time under its real name -- two module objects,
    # two `_REGISTRY` dicts. The handlers register into one and the loop reads
    # the other, so the consumer starts cleanly, connects, reads the stream and
    # reacts to nothing. Importing main from the canonical module puts the loop
    # and the handlers in the same one.
    from app.workers.consumers import main as canonical_main

    canonical_main()
