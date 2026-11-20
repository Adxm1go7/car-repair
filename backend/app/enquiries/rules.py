"""The rules for what a customer may send in an enquiry. Pure: no database."""

from typing import Final

from app.bookings.rules import reject_control_chars

DESCRIPTION_MIN: Final = 10
DESCRIPTION_MAX: Final = 1000  # the booking notes limit, so a description fits a booking's notes


def clean_description(value: str) -> str:
    value = reject_control_chars(value).strip()
    if not value:
        raise ValueError("Please describe the problem")
    if len(value) < DESCRIPTION_MIN:
        raise ValueError(f"Please describe the problem in at least {DESCRIPTION_MIN} characters")
    if len(value) > DESCRIPTION_MAX:
        raise ValueError(f"The description can be at most {DESCRIPTION_MAX} characters")
    return value
