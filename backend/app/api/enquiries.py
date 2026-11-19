"""The public enquiry form: a customer describes a problem they can't name. No login, no slot
and no payment; staff answer from the Enquiries page."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import AfterValidator, BaseModel
from sqlalchemy.orm import Session

from app.api.validation import caught_bot
from app.bookings.rules import (
    clean_email,
    clean_make_or_model,
    clean_name,
    clean_phone,
    clean_registration,
)
from app.clock import utc_now
from app.db import get_session
from app.enquiries.actions import EnquiryDetails, create_enquiry
from app.enquiries.rules import clean_description
from app.limits import limited

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]


class EnquiryIn(BaseModel):
    name: Annotated[str, AfterValidator(clean_name)]
    phone: Annotated[str, AfterValidator(clean_phone)]
    email: Annotated[str, AfterValidator(clean_email)]
    registration: Annotated[str, AfterValidator(clean_registration)]
    make: Annotated[str, AfterValidator(clean_make_or_model)]
    model: Annotated[str, AfterValidator(clean_make_or_model)]
    description: Annotated[str, AfterValidator(clean_description)]
    website: str | None = None  # the honeypot: people never see it


class EnquirySentOut(BaseModel):
    email: str  # where the "we've got it" email is going


@router.post("/enquiries", status_code=201, dependencies=[Depends(limited("enquiry"))])
def send_enquiry(
    body: EnquiryIn, incoming: Request, session: SessionDep, now: NowDep
) -> EnquirySentOut:
    if caught_bot(body.website, "/api/enquiries", incoming):
        return EnquirySentOut(email=body.email)  # looks sent; nothing is stored or emailed
    details = EnquiryDetails(
        name=body.name,
        phone=body.phone,
        email=body.email,
        registration=body.registration,
        make=body.make,
        model=body.model,
        description=body.description,
    )
    enquiry = create_enquiry(session, details, now)
    session.commit()
    return EnquirySentOut(email=enquiry.customer_email)
