"""The outbox relay: moves committed events from Postgres into Redis.

This is the only component that knows both systems exist. Producers write rows;
consumers read a stream; this closes the gap between them.

Run it as its own process:

    python -m app.workers.relay

Three properties worth understanding, because they are what make it safe:

1.  It reads with ``FOR UPDATE SKIP LOCKED``. Two relays running at once will
    not fight over the same rows and will not block each other -- each simply
    takes the next batch nobody has claimed. Without SKIP LOCKED a second relay
    would sit blocked on the first one's locks; without FOR UPDATE both would
    publish the same events.

2.  It publishes before marking published. If the process dies in between, the
    event is republished on restart. That is the deliberate trade: at-least-once
    delivery, never at-most-once. Consumers de-duplicate on ``event_id``.
    Marking first would give the opposite failure -- silently losing events --
    and a lost event cannot be detected, while a duplicate can.

3.  It claims the batch in one transaction and publishes inside it. The lock is
    held for the length of the XADD calls, which is why the batch is small.
"""

import logging
import signal
import time
from datetime import datetime, timezone

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  — completes the ORM registry for standalone runs
from app.core.database import SessionLocal
from app.modules.events.models import EventOutbox
from app.modules.events.stream import STREAM_KEY, STREAM_MAXLEN, encode, redis_url

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
# How long to wait when the outbox is empty. Short enough that the live stream
# feels immediate, long enough that an idle system is not hammering Postgres.
IDLE_SLEEP_SECONDS = 0.5


def publish_batch(db: Session, client, limit: int = BATCH_SIZE) -> int:
    """Claim, publish and mark one batch. Returns how many events went out.

    A plain function taking its session and its Redis client, so a test can
    drive one batch against a rolled-back transaction and a stub client without
    starting a process or touching a broker. `Relay` below is only the loop and
    the session lifecycle around it.
    """
    events = (
        db.execute(
            select(EventOutbox)
            .where(EventOutbox.published_at.is_(None))
            # Sequence order, not occurred_at: several events written in one
            # transaction share a timestamp to the microsecond, and "stock went
            # to zero" arriving before "stock moved" would be nonsense to
            # anyone reading the stream.
            .order_by(EventOutbox.sequence)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    if not events:
        return 0

    for event in events:
        client.xadd(STREAM_KEY, encode(event), maxlen=STREAM_MAXLEN, approximate=True)

    # Only after every XADD has returned. Marking first would turn a crash
    # mid-batch into silently lost events, and a lost event cannot be detected.
    published_at = datetime.now(timezone.utc)
    for event in events:
        event.published_at = published_at

    db.commit()
    logger.info("Relayed %d events.", len(events))
    return len(events)


class Relay:
    def __init__(self, client: redis.Redis | None = None, session_factory=SessionLocal):
        self.redis = client or redis.Redis.from_url(redis_url())
        self.session_factory = session_factory
        self._stopping = False

    def stop(self, *_args) -> None:
        """Finish the batch in flight, then exit. Wired to SIGTERM and SIGINT."""
        logger.info("Relay stopping after current batch.")
        self._stopping = True

    def drain_once(self) -> int:
        db = self.session_factory()
        try:
            return publish_batch(db, self.redis)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        logger.info("Relay started. Watching event_outbox -> %s", STREAM_KEY)
        while not self._stopping:
            try:
                published = self.drain_once()
            except Exception:
                # A relay that exits on a transient database blip stops the
                # entire event system until someone notices. Log it and retry.
                logger.exception("Relay batch failed; retrying.")
                published = 0
                time.sleep(2)

            if published == 0:
                time.sleep(IDLE_SLEEP_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    Relay().run()


if __name__ == "__main__":
    main()
