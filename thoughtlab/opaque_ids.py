"""Canonical type-neutral identifiers for controlled synthetic experiments."""

from __future__ import annotations

import random
import re
import secrets

CROCKFORD_BASE32_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
OPAQUE_ID_PREFIX = "ID_"
OPAQUE_ID_BODY_LENGTH = 26
OPAQUE_ID_BITS = OPAQUE_ID_BODY_LENGTH * 5

_OPAQUE_ID_RE = re.compile(
    rf"^{re.escape(OPAQUE_ID_PREFIX)}"
    rf"[{CROCKFORD_BASE32_ALPHABET}]{{{OPAQUE_ID_BODY_LENGTH}}}$"
)


def generate_opaque_id(*, rng: random.Random | None = None) -> str:
    """Return a role-free 130-bit identifier in canonical Crockford base32.

    The identifier deliberately accepts no semantic kind or label. Pass a
    seeded ``random.Random`` only when a reproducible experiment manifest is
    required; otherwise generation uses ``secrets``.
    """
    choose = secrets.choice if rng is None else rng.choice
    body = "".join(
        choose(CROCKFORD_BASE32_ALPHABET) for _ in range(OPAQUE_ID_BODY_LENGTH)
    )
    return f"{OPAQUE_ID_PREFIX}{body}"


def is_opaque_id(value: object) -> bool:
    """Return whether *value* has the canonical type-neutral identifier form."""
    return isinstance(value, str) and _OPAQUE_ID_RE.fullmatch(value) is not None
