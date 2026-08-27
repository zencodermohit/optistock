"""Whose quota a request spends.

The limits themselves are ordinary. What is worth testing is the thing that
was wrong in production: behind a reverse proxy, counting the socket peer
counts the PROXY, so every visitor shares one bucket. Six failed logins from
one laptop then refused a correct login with 429 -- a denial of service anyone
could trigger, dressed up as brute-force protection.

Two properties have to hold at once, and they pull in opposite directions:

*   a client must not be able to choose its own bucket, or the limit is
    decorative;
*   distinct clients must not share one, or the limit is a shared fuse.

So the tests below are mostly about the first: what happens when a caller
sends headers designed to escape the count.
"""

from types import SimpleNamespace

import pytest

from app.core.rate_limit import REAL_IP_HEADER, client_identity


def request_from(peer, headers=None):
    """A stand-in carrying only what the key function reads."""
    return SimpleNamespace(
        client=SimpleNamespace(host=peer) if peer else None,
        headers={k.lower(): v for k, v in (headers or {}).items()},
    )


def test_the_proxys_own_address_is_never_the_answer():
    """The bug this replaces. Every request arrived as the nginx container, so
    every limit was one bucket shared by the whole internet."""
    first = client_identity(request_from("172.18.0.7", {REAL_IP_HEADER: "203.0.113.9"}))
    second = client_identity(
        request_from("172.18.0.7", {REAL_IP_HEADER: "198.51.100.4"})
    )

    assert first == "203.0.113.9"
    assert second == "198.51.100.4"
    assert first != second, "two clients behind one proxy shared a bucket"


def test_a_public_caller_cannot_hand_us_an_identity():
    """The header is only as trustworthy as the hop that set it. A request
    arriving straight off the internet has not passed our nginx, so anything
    it claims about itself is just a claim."""
    # A genuinely public address. 203.0.113.x looks public but Python counts
    # the documentation ranges as private, so using one here tested nothing --
    # which is why the trust list now names its networks explicitly.
    peer = "8.8.8.8"
    spoofed = client_identity(request_from(peer, {REAL_IP_HEADER: "10.0.0.1"}))

    assert spoofed == peer, "trusted a header from an untrusted hop"


@pytest.mark.parametrize("invented", ["1.2.3.4", "8.8.8.8", "9.9.9.9"])
def test_forwarded_for_is_ignored_however_it_is_dressed(invented):
    """X-Forwarded-For is set with $proxy_add_x_forwarded_for, which APPENDS to
    whatever the client sent. Its first element is therefore attacker-chosen,
    and honouring it would let one caller mint a fresh bucket per request by
    inventing an address. X-Real-IP is overwritten by nginx and cannot be
    influenced, which is why that is the one read."""
    identity = client_identity(
        request_from("172.18.0.7", {"x-forwarded-for": f"{invented}, 172.18.0.7"})
    )

    assert identity != invented
    # With no X-Real-IP present it falls back to the peer, which is strict
    # rather than permissive -- the safe direction to be wrong in.
    assert identity == "172.18.0.7"


def test_a_client_behind_the_proxy_keeps_one_bucket_across_requests():
    """The other half: the same person must not get a new allowance per
    request, or the limit never triggers."""
    calls = [
        client_identity(request_from("172.18.0.7", {REAL_IP_HEADER: "203.0.113.9"}))
        for _ in range(5)
    ]
    assert len(set(calls)) == 1


@pytest.mark.parametrize(
    "peer",
    ["127.0.0.1", "::1", "10.1.2.3", "192.168.0.4", "172.18.0.7"],
)
def test_local_and_private_hops_may_speak_for_a_client(peer):
    assert client_identity(request_from(peer, {REAL_IP_HEADER: "203.0.113.9"})) == (
        "203.0.113.9"
    )


def test_nothing_here_raises_on_a_malformed_request():
    """A limiter that throws takes the endpoint down with it, which is a
    heavier failure than a request that slipped through uncounted."""
    assert client_identity(request_from(None)) == "unknown"
    assert client_identity(request_from("not-an-address")) == "not-an-address"
    assert client_identity(request_from("172.18.0.7", {REAL_IP_HEADER: "  "})) == (
        "172.18.0.7"
    )
