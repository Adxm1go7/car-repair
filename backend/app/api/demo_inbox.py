"""The live demo's Demo inbox: the emails the worker kept instead of sending.

Public and read-only, and only on the demo site (main.py includes it when DEMO_SITE is on).
It is one shared inbox, so every visitor sees every customer email; the pages say so.
Staff emails (invites, password resets) are kept but never shown, so nobody can use a reset
link to take over a shared demo login.
"""

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.validation import ResourceId
from app.models import DemoInboxEmail
from app.staff.deps import SessionDep

router = APIRouter(prefix="/demo-inbox")

STAFF_TEMPLATES: Final = ("staff_invite", "password_reset")
LIST_LIMIT: Final = 50
NOT_FOUND: Final = HTTPException(status_code=404, detail="No such email")


class InboxSummaryOut(BaseModel):
    id: int
    to: str
    subject: str
    sent_at: datetime


class InboxEmailOut(InboxSummaryOut):
    text: str
    html: str


def _summary(email: DemoInboxEmail) -> InboxSummaryOut:
    return InboxSummaryOut(
        id=email.id, to=email.recipient, subject=email.subject, sent_at=email.sent_at
    )


@router.get("")
def list_inbox(
    session: SessionDep, to: Annotated[str | None, Query(max_length=254)] = None
) -> list[InboxSummaryOut]:
    """The latest customer emails, newest first; `to` keeps only one recipient's."""
    query = select(DemoInboxEmail).where(DemoInboxEmail.template.not_in(STAFF_TEMPLATES))
    if to is not None and to.strip():
        query = query.where(func.lower(DemoInboxEmail.recipient) == to.strip().lower())
    emails = session.scalars(query.order_by(DemoInboxEmail.id.desc()).limit(LIST_LIMIT))
    return [_summary(email) for email in emails]


@router.get("/{email_id}")
def read_email(email_id: ResourceId, session: SessionDep) -> InboxEmailOut:
    email = session.get(DemoInboxEmail, email_id)
    if email is None or email.template in STAFF_TEMPLATES:
        raise NOT_FOUND
    return InboxEmailOut(**_summary(email).model_dump(), text=email.text, html=email.html)
