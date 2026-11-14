"""Build webhook requests signed the way Stripe signs them, from the JSON fixtures.

Stripe's `Stripe-Signature` header is `t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>">`,
keyed with the endpoint's webhook secret.
"""

import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "stripe"
WEBHOOK_SECRET = "whsec_test_not_real"  # noqa: S105 - only ever used by tests


def signed(
    payload: bytes, secret: str = WEBHOOK_SECRET, timestamp: int | None = None
) -> dict[str, str]:
    t = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={t},v1={digest}", "Content-Type": "application/json"}


def event(name: str, *, event_id: str | None = None, object_id: str | None = None) -> bytes:
    """A fixture event as bytes, optionally with a different event id or object id."""
    body: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    if event_id is not None:
        body["id"] = event_id
    if object_id is not None:
        body["data"]["object"]["id"] = object_id
    return json.dumps(body).encode()
