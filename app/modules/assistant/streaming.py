"""Making an answer safe to show before it is finished.

validate_answer in validation.py is written for a complete answer. It reads the
whole string, finds a leaked key or a control character, and rewrites it. That
works because nothing has been shown to anyone yet.

Streaming breaks that assumption. The point of streaming is that the reader sees
the first sentence while the last one is still being written, which means text
leaves this process before there is a whole answer to check. Run the same
checks naively on each fragment and they fail in both directions: a key split
across two fragments matches neither half, and text already sent cannot be
unsent.

So this module streams with a hold-back. Text is released only once it is
certain no rewrite can still apply to it, which needs two rules:

*   **Nothing is released while it could still become a secret.** Every pattern
    in validation.py starts with a distinctive marker -- ``AIza``, ``sk-ant-``,
    ``eyJ``, ``postgres://``. If one appears in the unreleased tail, everything
    from that point is held until the pattern either completes (and is redacted)
    or the answer ends (and it was a false alarm). A marker can also be split
    across fragments, so a tail that is a *prefix* of a marker holds too.
*   **Nothing is released while it could still be a pseudonym.** In demo mode
    the model writes ``SKU-7A3F21`` and the reader must see the real SKU. Those
    tokens are a fixed ten characters, so holding a short tail guarantees a
    token is whole before it is unmasked.

What is deliberately NOT held back is the part of validation that only annotates.
A claim of having placed an order is answered with a warning under the message,
not by silently deleting the sentence -- validation.py argues that case and this
module does not reopen it. Those checks run once at the end, on the full text,
exactly as before.

The contract is that concatenating everything ``feed()`` returns, plus what
``finish()`` returns, equals what ``validate_answer`` would have produced for
the same text. There is a test that asserts precisely that against the
non-streaming path, because the moment those two disagree, streaming has
quietly become a way around the output filter.
"""

from typing import List, Optional

from app.modules.assistant.redaction import Redactor
from app.modules.assistant.validation import (
    MAX_ANSWER_CHARS,
    _CONTROL,
    _SECRETS,
)

#: The leading literal of each pattern in validation._SECRETS. Kept beside that
#: list rather than derived from it: a regex cannot be asked for its prefix
#: reliably, and a wrong guess here fails open. There is a test that every
#: pattern in _SECRETS is covered by a marker below.
SECRET_MARKERS = (
    "sk-ant-",
    "AIza",
    "AQ.",
    "ghp_",
    "eyJ",
    "postgres://",
    "postgresql://",
)

#: Longest pseudonym a Redactor issues is "SKU-" plus six hex characters. Held
#: back so a token split across two fragments is whole before it is unmasked.
_PSEUDONYM_WIDTH = 12

_LONGEST_MARKER = max(len(marker) for marker in SECRET_MARKERS)


def _hold_from(pending: str) -> int:
    """Index of the first character that must not be released yet.

    len(pending) means everything is safe to release.
    """
    earliest = len(pending)

    # A complete marker anywhere in the tail: hold from it, because the
    # characters that would finish the secret have not arrived.
    for marker in SECRET_MARKERS:
        found = pending.find(marker)
        if found != -1:
            earliest = min(earliest, found)

    # A marker split across fragments: the tail ends with the start of one.
    # Checked separately because find() cannot see a half-written marker.
    window = min(len(pending), _LONGEST_MARKER - 1)
    for size in range(window, 0, -1):
        tail = pending[-size:]
        if any(marker.startswith(tail) for marker in SECRET_MARKERS):
            earliest = min(earliest, len(pending) - size)
            break

    return earliest


class AnswerGuard:
    """Releases an answer in pieces, but only pieces that are already final.

    Not reusable across answers; one per turn, like the Redactor it wraps.
    """

    def __init__(self, redactor: Optional[Redactor] = None) -> None:
        self._redactor = redactor
        self._pending = ""
        #: Everything released so far, so the end-of-stream checks see the same
        #: string the reader saw.
        self.released = ""
        self.flags: List[str] = []
        self._truncated = False

    def feed(self, chunk: str) -> str:
        """Take a fragment from the model, return what is safe to show now.

        Returns "" often and that is normal -- it means the fragment landed
        inside something that cannot be judged yet.
        """
        if self._truncated or not chunk:
            return ""

        cleaned = _CONTROL.sub("", chunk)
        if cleaned != chunk and "control_characters" not in self.flags:
            self.flags.append("control_characters")

        self._pending += cleaned

        cut = _hold_from(self._pending)
        # Also hold a short tail so a pseudonym arriving in halves is whole
        # before anyone tries to unmask it.
        cut = min(cut, max(0, len(self._pending) - _PSEUDONYM_WIDTH))
        # ...and having held it, do not then slice through the middle of one.
        # The tail rule guarantees a token is COMPLETE in the buffer; it says
        # nothing about where the release boundary falls, and a cut inside a
        # token unmasks neither half.
        cut = self._before_any_token(self._pending, cut)
        if cut <= 0:
            return ""

        return self._release(self._pending[:cut], remainder=self._pending[cut:])

    def _before_any_token(self, pending: str, cut: int) -> int:
        """Pull `cut` back so no issued pseudonym straddles it."""
        if self._redactor is None or not self._redactor.demo:
            return cut
        for token in self._redactor.issued:
            start = pending.find(token)
            while start != -1 and start < cut:
                if start + len(token) > cut:
                    cut = start
                start = pending.find(token, start + 1)
        return cut

    def finish(self) -> str:
        """Release whatever is left, now that no more text can arrive."""
        if self._truncated or not self._pending:
            return ""
        return self._release(self._pending, remainder="")

    def _release(self, text: str, remainder: str) -> str:
        """Apply the rewriting checks to `text` and hand it over."""
        for pattern in _SECRETS:
            if pattern.search(text):
                if "secret_redacted" not in self.flags:
                    self.flags.append("secret_redacted")
                text = pattern.sub("[redacted]", text)

        if self._redactor is not None:
            text = self._redactor.unmask_text(text)

        # The cap is on what the reader receives, so it is measured against
        # released text rather than against what the model generated.
        room = MAX_ANSWER_CHARS - len(self.released)
        if len(text) >= room:
            text = text[:room]
            self._truncated = True
            if "truncated" not in self.flags:
                self.flags.append("truncated")
            remainder = ""

        self._pending = remainder
        self.released += text
        return text

    @property
    def truncated(self) -> bool:
        return self._truncated
