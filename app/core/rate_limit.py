"""Who a request is counted against, and where the tally is kept.

The limits themselves live on the endpoints. This module answers the question
underneath them, which turned out to be the one that mattered: WHOSE quota is
this request spending?

The first version answered "the remote address", which behind a reverse proxy
is the proxy. Every visitor on earth arrived as 172.18.0.7, so every limit was
one shared bucket rather than one per client. Measured against production
before changing anything: six failed logins from a laptop, then a correct
login refused with 429. Six curl commands could lock every user out of the
site for a minute -- brute-force protection that doubles as a denial of
service, which is a worse trade than having no limit at all.

WHY X-Real-IP AND NOT X-Forwarded-For. Both are set by our nginx, and only one
of them is safe:

    proxy_set_header X-Real-IP $remote_addr;                  overwrites
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;  appends

X-Forwarded-For keeps whatever the client sent and appends the peer, so its
first element is attacker-controlled -- a client sending
`X-Forwarded-For: 1.2.3.4` gets a fresh bucket per made-up address and the
limit stops existing. X-Real-IP is overwritten by nginx on every request, so a
client cannot influence it.

AND ONLY FROM A PROXY WE BELIEVE. A header is only as trustworthy as the hop
that set it, so it is read only when the immediate peer is a private or
loopback address. In this deployment nothing else can reach the application:
nginx is on the compose network and the API port is published to 127.0.0.1
only. If that ever changes and the app is exposed directly, a public peer is
not trusted and the limit falls back to counting the real socket -- the
failure mode is "stricter than intended", never "bypassable".
"""

import ipaddress
import logging
from typing import Optional

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Header nginx overwrites with the true peer. See the module docstring for
#: why the more obvious X-Forwarded-For is not used.
REAL_IP_HEADER = "x-real-ip"


#: Hops allowed to tell us who the client is: our own machine, and the private
#: ranges a container network is built from.
#:
#: Spelled out rather than using ipaddress.is_private, which is broader than it
#: sounds -- it also covers the documentation ranges (192.0.2.0/24,
#: 198.51.100.0/24, 203.0.113.0/24) and carrier-grade NAT. None of those is a
#: hop on our network, and a trust list should say exactly what it trusts.
TRUSTED_HOPS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "fc00::/7",
    )
)


def _from_a_proxy_we_trust(host: Optional[str]) -> bool:
    """Whether a hop at `host` is allowed to tell us who the client is."""
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A hostname rather than an address. Not something a socket peer
        # normally is, and not something to extend trust to.
        return False
    return any(address in network for network in TRUSTED_HOPS)


def client_identity(request: Request) -> str:
    """The address this request is counted against.

    Falls back to the peer, and finally to a single shared key, because a
    limiter that raises is a limiter that takes the endpoint down with it.
    """
    peer = request.client.host if request.client else None

    if _from_a_proxy_we_trust(peer):
        # Stripped BEFORE it is judged. A header of "   " is truthy, and
        # returning it stripped handed back an empty string -- which is a
        # perfectly good dictionary key, so every request carrying a blank
        # header would have shared one bucket. Caught by a test that fed it
        # whitespace on purpose.
        forwarded = (request.headers.get(REAL_IP_HEADER) or "").strip()
        if forwarded:
            return forwarded

    return peer or "unknown"


def _storage_uri() -> Optional[str]:
    """Where the counters live.

    Redis when configured, so a restart does not hand everyone a fresh
    allowance and a second replica cannot double every limit. In-memory
    otherwise, which is what the test suite runs on -- it resets the limiter
    between tests, and a shared Redis would make those tests depend on each
    other.
    """
    if not settings.RATE_LIMIT_STORAGE:
        return None
    return settings.RATE_LIMIT_STORAGE


#: swallow_errors because the alternative is worse. If the counter store is
#: briefly unreachable, the choice is to serve the request unlimited or to
#: fail it outright, and a rate limiter should never be the reason a working
#: application returns 500.
limiter = Limiter(
    key_func=client_identity,
    storage_uri=_storage_uri(),
    swallow_errors=True,
)
