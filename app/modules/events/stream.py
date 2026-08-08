"""The Redis Streams side of the event backbone.

Redis Streams rather than Kafka. The workload is thousands of events a day, not
millions a second, and Kafka's answer to that scale costs a ZooKeeper-or-KRaft
cluster, a schema registry and a partition plan to operate. A Stream is an
append-only log with consumer groups, offsets and acknowledgements — the four
properties this system actually uses — and it runs in a container that is
already here for caching.

The outbox is what makes that a cheap decision rather than a permanent one.
Producers write rows to Postgres and know nothing about Redis; only the relay in
`app/workers/relay.py` does. Swapping the broker means rewriting one file.
"""

import json
from typing import Any, Dict

from app.core.config import settings

# One stream for every tenant's events. Splitting per company would multiply
# connections and consumer groups by the number of tenants, and every consumer
# already has to check `company_id` on each message anyway — a shared stream
# makes that check impossible to forget.
STREAM_KEY = "optistock:events"

# Trimmed to a rough cap on XADD. Redis is the transport, not the record: the
# durable history is the outbox table, and this only has to hold enough for a
# reconnecting browser or a briefly-stopped worker to catch up.
STREAM_MAXLEN = 10_000

# Work-distributing consumers (alerting, projections) join this group so each
# message is handled once across all replicas. Browsers do NOT use it — a live
# view wants every event, not a share of them, so the SSE endpoint plain-reads
# the stream instead.
CONSUMER_GROUP = "optistock-workers"


def redis_url() -> str:
    return settings.REDIS_URL


def encode(event) -> Dict[str, str]:
    """Flatten an outbox row into the flat string map a stream entry holds.

    `payload` is nested, so it is carried as a JSON string in one field rather
    than exploded into the entry. Exploding it would put the producer's payload
    shape into the transport's schema, and then adding a field to a payload
    would be a transport change.
    """
    return {
        "event_id": str(event.event_id),
        "sequence": str(event.sequence),
        "company_id": str(event.company_id),
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": str(event.aggregate_id),
        "occurred_at": event.occurred_at.isoformat(),
        "payload": json.dumps(event.payload, default=str),
    }


def decode(fields: Dict[Any, Any]) -> Dict[str, Any]:
    """Turn a stream entry back into a dict, whatever byte-ness Redis returned.

    decode_responses is not assumed: a client configured either way should be
    able to read this, and getting it wrong yields b'event_type' keys that
    silently match nothing.
    """

    def s(value):
        return value.decode() if isinstance(value, bytes) else value

    decoded = {s(k): s(v) for k, v in fields.items()}
    raw = decoded.get("payload")
    decoded["payload"] = json.loads(raw) if raw else {}
    return decoded
