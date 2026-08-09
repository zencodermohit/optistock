"""What the model is allowed to see, before it sees it.

The tools query real rows. This is the layer between those rows and the request
that leaves the building, and it exists because the destination is a third
party: Gemini's free tier states plainly that content is used to improve
Google's products. Whatever is sent is sent for good.

Two modes, set by LLM_DATA_MODE:

    production  Nothing is altered. The operator has accepted the provider's
                terms for their real data.
    demo        Identifiers are replaced with stable pseudonyms before the
                payload leaves the process.

The pseudonyms are the part worth explaining. Blanking a SKU would be safer and
useless: an answer that cannot name what it is talking about is not an answer,
and the model would lose the thread between "the one that is out of stock" and
"the one you should reorder". A stable pseudonym keeps every relationship the
model needs -- the same product is the same token everywhere, two products are
visibly different -- while carrying nothing that identifies a real catalogue.

Citations are built from the UNMASKED rows and never pass through here, so the
screen still shows real SKUs and warehouse names. The masking is on the outbound
side only: the model reasons in pseudonyms, the user reads the truth.

And because a `Redactor` remembers what it substituted for the life of one
request, the pseudonyms the model writes back into its answer are turned into
real identifiers again before the answer is rendered. The user never sees a
hash; the provider never sees a SKU.
"""

import hashlib
import re
from typing import Any, Dict, List

from app.core.config import settings

# Fields replaced in demo mode. Names and free text are left alone: a product
# called "Standing Desk Pro 60\"" tells an attacker nothing, and stripping it
# would make every answer unreadable. Identifiers are what tie a leak back to a
# real business.
MASKED_FIELDS = frozenset({"sku", "device_id", "reference", "customer_name"})

# Keys whose values are themselves rows or lists of rows.
_CONTAINER_KEYS = frozenset(
    {"products", "stock_lines", "alerts", "events", "warehouses", "evidence", "payload"}
)


def is_demo_mode() -> bool:
    return settings.LLM_DATA_MODE.strip().lower() != "production"


def pseudonym(value: str, prefix: str = "SKU") -> str:
    """A stable, non-reversible stand-in for one identifier.

    Deterministic so the same product is the same token across every tool call
    in a conversation -- without that, the model cannot tell that the item it
    found low on stock is the item it was asked about. Hashed rather than
    counted so two separate requests agree, and salted with the secret key so
    the mapping cannot be rebuilt by anyone who guesses the input space, which
    for SKUs is small enough to enumerate.
    """
    digest = hashlib.sha256(
        f"{settings.SECRET_KEY}:{value}".encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:6].upper()}"


class Redactor:
    """Masks outbound payloads and restores inbound text, for one request.

    Stateful on purpose. The map of pseudonym -> real identifier is what makes
    the answer readable: the model writes "SKU-7A3F is below its reorder point"
    and this turns it back into "WIDGET-9" before it reaches the screen. The map
    lives for the length of one request and is never persisted -- it is a
    convenience for rendering, not a store.
    """

    def __init__(self) -> None:
        self.demo = is_demo_mode()
        self._real_for: Dict[str, str] = {}

    def mask(self, payload: Any) -> Any:
        """Return `payload` with identifiers replaced, recording each swap.

        Recursive because tool results nest: a stock line inside a list inside
        a dict. Returns the original object untouched in production mode, so
        the common path costs nothing.
        """
        if not self.demo:
            return payload
        return self._walk(payload)

    def unmask_text(self, text: str) -> str:
        """Put the real identifiers back into the model's prose.

        Only substitutes tokens this instance actually issued. A pseudonym the
        model invented rather than read has no entry, and is left exactly as
        written -- inventing a plausible mapping would be worse than showing
        the reader something obviously wrong.
        """
        if not self.demo or not self._real_for or not text:
            return text

        pattern = re.compile(
            "|".join(re.escape(token) for token in sorted(self._real_for, key=len, reverse=True))
        )
        return pattern.sub(lambda m: self._real_for[m.group(0)], text)

    @property
    def substitutions(self) -> int:
        return len(self._real_for)

    def _walk(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._mask_field(key, item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._walk(item) for item in value]
        return value

    def _mask_field(self, key: str, value: Any) -> Any:
        if key in MASKED_FIELDS and isinstance(value, str) and value:
            token = pseudonym(value)
            self._real_for[token] = value
            return token
        if key in _CONTAINER_KEYS or isinstance(value, (dict, list)):
            return self._walk(value)
        return value


def redact(payload: Any) -> Any:
    """Mask a payload without keeping the mapping.

    For callers that only need the outbound half. Pseudonyms are deterministic,
    so this agrees with any `Redactor` on the same input.
    """
    return Redactor().mask(payload)


def describe_mode() -> Dict[str, Any]:
    """What the UI shows so the boundary is visible rather than assumed."""
    demo = is_demo_mode()
    return {
        "mode": "demo" if demo else "production",
        "masked_fields": sorted(MASKED_FIELDS) if demo else [],
        "note": (
            "Identifiers are replaced with stable pseudonyms before anything "
            "reaches the model. Citations below are built from the real rows."
            if demo
            else "Real data is sent to the model provider."
        ),
    }


def masked_field_names() -> List[str]:
    return sorted(MASKED_FIELDS)
