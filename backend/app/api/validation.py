"""Input checks shared by public routes, so availability and holds refuse the same things."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Service
from app.repositories.availability import find_active_services

MAX_SERVICES = 20
MAX_SLUG_LENGTH = 64  # Service.slug is String(64)


def reject(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def resolve_services(session: Session, slugs: list[str]) -> list[Service]:
    """The active services for these slugs, in the order given, or a 422."""
    if not slugs or any(not slug for slug in slugs):
        raise reject("Choose at least one service")
    if len(slugs) > MAX_SERVICES:
        raise reject(f"Choose at most {MAX_SERVICES} services")
    # A NUL can't be sent to PostgreSQL at all, and no slug is longer than its column.
    if any("\x00" in slug or len(slug) > MAX_SLUG_LENGTH for slug in slugs):
        raise reject("Unknown service")
    if len(set(slugs)) != len(slugs):
        raise reject("Each service can only be chosen once")
    found = find_active_services(session, slugs)
    if len(found) != len(slugs):
        missing = sorted(set(slugs) - {service.slug for service in found})
        raise reject(f"Unknown service: {', '.join(missing)}")
    return found


def check_bookable_date(day: date, now: datetime, zone: ZoneInfo, window_days: int) -> None:
    """A 422 unless `day` is between today and the end of the window, in garage time."""
    today = now.astimezone(zone).date()
    if day < today:
        raise reject("That date has already passed")
    if day > today + timedelta(days=window_days):
        raise reject(f"Bookings open at most {window_days} days ahead")
