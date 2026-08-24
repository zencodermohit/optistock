"""The output filter must not be weakened by streaming.

Everything here is one property stated several ways: a reader watching an answer
arrive in fragments must end up with exactly the string that validate_answer
would have produced for the whole thing. If that ever stops being true,
streaming has become a way around the filter, and the interesting cases are the
ones where a secret is split across fragments -- which is the shape a naive
per-chunk filter gets wrong.
"""

import pytest

from app.modules.assistant.redaction import Redactor
from app.modules.assistant.streaming import (
    SECRET_MARKERS,
    AnswerGuard,
    _hold_from,
)
from app.modules.assistant.validation import _SECRETS, MAX_ANSWER_CHARS, validate_answer


def drain(text: str, sizes, redactor=None) -> str:
    """Feed `text` through a guard in fragments of the given sizes."""
    guard = AnswerGuard(redactor)
    out = []
    index = 0
    for size in sizes:
        if index >= len(text):
            break
        out.append(guard.feed(text[index : index + size]))
        index += size
    if index < len(text):
        out.append(guard.feed(text[index:]))
    out.append(guard.finish())
    return "".join(out), guard


def every_split(text: str):
    """Fragment sizes worth trying: one big piece, single characters, and
    every possible two-way split -- the last one is where a marker straddles
    a boundary."""
    yield [len(text)]
    yield [1] * len(text)
    yield [3] * (len(text) // 3 + 1)
    for cut in range(1, len(text)):
        yield [cut, len(text) - cut]


SECRETS_IN_PROSE = [
    "Your key is AIzaSyA1234567890abcdefghijklmnopqrstu and it works.",
    "Use sk-ant-abcdefghijklmnop for that.",
    "token AQ.Ab8RN6JabcdefghijklmnopQ done",
    "creds ghp_abcdefghijklmnopqrstuvwxyz0123456789 here",
    "db postgres://user:pw@host/db now",
    "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NX0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
]


@pytest.mark.parametrize("text", SECRETS_IN_PROSE)
def test_secret_never_escapes_however_it_is_split(text):
    """The whole point. A key must not reach the reader because it happened to
    arrive in two pieces."""
    expected = validate_answer(text).text
    for sizes in every_split(text):
        streamed, guard = drain(text, sizes)
        assert streamed == expected, f"leaked with sizes={sizes[:4]}"
        assert "secret_redacted" in guard.flags
        # Belt and braces: the raw secret must not appear even in part.
        for pattern in _SECRETS:
            assert not pattern.search(streamed)


def test_every_secret_pattern_has_a_marker():
    """_hold_from works off literal markers. If someone adds a pattern to
    _SECRETS without adding its marker here, streaming would release the
    secret while the non-streaming path still caught it -- a divergence that
    would be invisible until it mattered."""
    for text in SECRETS_IN_PROSE:
        assert _hold_from(text) < len(text), f"no marker matched: {text[:30]}"
    assert len(SECRET_MARKERS) >= len(_SECRETS)


@pytest.mark.parametrize(
    "text",
    [
        "Nothing wrong with this answer at all.",
        "Stock is low. Reorder soon.",
        "A number: 12 units, 40 reorder point.",
        "",
    ],
)
def test_clean_text_is_unchanged(text):
    for sizes in every_split(text) if text else [[1]]:
        streamed, guard = drain(text, sizes)
        assert streamed == validate_answer(text).text if text else streamed == ""
        assert "secret_redacted" not in guard.flags


def test_control_characters_are_stripped_like_the_batch_path():
    text = "Stock\x00 is\x07 low."
    streamed, guard = drain(text, [1] * len(text))
    assert streamed == validate_answer(text).text
    assert "control_characters" in guard.flags


def test_pseudonyms_are_unmasked_even_when_split(monkeypatch):
    """A pseudonym arriving in halves must still become the real SKU."""
    monkeypatch.setattr("app.modules.assistant.redaction.is_demo_mode", lambda: True)
    redactor = Redactor()
    masked = redactor.mask({"sku": "WIDGET-9"})
    token = masked["sku"]
    text = f"{token} is below its reorder point."

    for sizes in every_split(text):
        streamed, _ = drain(text, sizes, redactor)
        assert "WIDGET-9" in streamed, f"pseudonym leaked with sizes={sizes[:4]}"
        assert token not in streamed


def test_long_answers_are_capped_at_the_same_ceiling():
    text = "x" * (MAX_ANSWER_CHARS + 500)
    streamed, guard = drain(text, [500] * 30)
    assert len(streamed) == MAX_ANSWER_CHARS
    assert guard.truncated and "truncated" in guard.flags


def test_nothing_is_released_before_it_is_decidable():
    """While a marker is open, the guard holds. This is what makes the
    property above achievable at all."""
    guard = AnswerGuard()
    # Prose before the marker is decided and may go out. The marker may not,
    # because the characters that settle whether it is a key have not arrived
    # -- so the guard holds it, and keeps holding while the key streams in.
    seen = ""
    for fragment in (
        "your key is AIza",
        "SyA1234567890abcdefghijklmnopqrstu",
        " and that is it, a reasonably long tail follows here.",
    ):
        released = guard.feed(fragment)
        seen += released
        assert "AIza" not in seen, f"marker released after {fragment[:12]!r}"
    seen += guard.finish()
    assert "[redacted]" in seen
    assert (
        seen
        == validate_answer(
            "your key is AIzaSyA1234567890abcdefghijklmnopqrstu"
            " and that is it, a reasonably long tail follows here."
        ).text
    )
