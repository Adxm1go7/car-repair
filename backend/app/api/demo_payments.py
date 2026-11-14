"""Demo payments, so a fresh clone with no Stripe keys can still book end to end.

`create_app` registers this router only when no Stripe key is set; with Stripe configured,
and therefore always in production and CI, these routes don't exist.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.db import get_session
from app.payments.demo_provider import DemoProvider
from app.payments.service import complete_deposit
from app.repositories.bookings import get_booking_for_update_by_id
from app.repositories.payments import find_payment

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]

NOT_FOUND = HTTPException(status_code=404, detail="Payment not found")


class DemoPayIn(BaseModel):
    outcome: Literal["pay", "decline"]


class DemoPayOut(BaseModel):
    status: str


@router.post("/demo/checkout/{demo_session}")
def demo_pay(demo_session: str, body: DemoPayIn, session: SessionDep, now: NowDep) -> DemoPayOut:
    """Pretend the customer paid (or their card was declined) in the demo payment box."""
    provider = DemoProvider(session)
    found = find_payment(session, provider.name, demo_session)
    if found is None or found.kind != "deposit":
        raise NOT_FOUND
    booking = get_booking_for_update_by_id(session, found.booking_id)
    if booking is None:
        raise NOT_FOUND
    if found.status == "paid":
        return DemoPayOut(status=booking.status)  # a second tap changes nothing
    if found.status != "open":
        raise NOT_FOUND  # released: the form is closed, as Stripe's would be
    if body.outcome == "decline":
        raise HTTPException(status_code=402, detail="Your card was declined (demo)")
    provider.mark_paid(demo_session)
    complete_deposit(session, provider, demo_session, now)
    session.commit()
    return DemoPayOut(status=booking.status)
