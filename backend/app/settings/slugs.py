"""Slugs for things admins add. A slug is made once from the name and never changes, because
it can be in links people already have (`?services=`)."""

import re
from collections.abc import Collection
from typing import Final

MAX_LENGTH: Final = 64  # the slug columns are String(64)
_NOT_ALPHANUMERIC: Final = re.compile(r"[^a-z0-9]+")


def _cut(text: str, length: int) -> str:
    return text[:length].strip("-")


def make_slug(name: str, taken: Collection[str]) -> str:
    """Lowercase, runs of anything but a–z and 0–9 as one dash, at most 64 characters, and
    `-2`, `-3`… on the end if it's taken. A name with no letters or digits becomes `item`."""
    base = _cut(_NOT_ALPHANUMERIC.sub("-", name.lower()), MAX_LENGTH) or "item"
    if base not in taken:
        return base
    number = 2
    while True:
        suffix = f"-{number}"
        candidate = _cut(base, MAX_LENGTH - len(suffix)) + suffix
        if candidate not in taken:
            return candidate
        number += 1
