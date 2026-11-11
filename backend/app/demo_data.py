"""Fictional demo garage. The only place catalogue values appear in code.

The seed inserts these into an empty database. After that the database is the
source of truth: editing this file changes an existing database only after a
reset (`docker compose down -v`).
"""

from dataclasses import dataclass
from datetime import time
from typing import Final


@dataclass(frozen=True)
class DemoService:
    slug: str
    name: str
    category: str
    description: str
    duration_minutes: int
    price_from_pence: int
    price_to_pence: int | None
    bay_type_slug: str
    approval_mode: str


DEMO_GARAGE_CONTACT: Final[dict[str, str]] = {
    "name": "Hillside Motors",
    "address": "12 Station Road, Anytown, AT1 2CD",
    "phone": "01632 960123",  # Ofcom drama range: never a real number
    "email": "bookings@example.com",
}

# (slug, name)
DEMO_BAY_TYPES: Final[list[tuple[str, str]]] = [
    ("mot", "MOT ramp"),
    ("general", "General bay"),
]

# (slug, name, bay type slug)
DEMO_BAYS: Final[list[tuple[str, str, str]]] = [
    ("mot-bay", "MOT bay", "mot"),
    ("bay-1", "Bay 1", "general"),
    ("bay-2", "Bay 2", "general"),
    ("bay-3", "Bay 3", "general"),
]

# Display order is list order.
DEMO_SERVICES: Final[list[DemoService]] = [
    DemoService(
        "mot-test", "MOT test", "MOT",
        "The annual roadworthiness test, with a printed report of anything we find.",
        60, 5485, None, "mot", "instant",
    ),
    DemoService(
        "oil-filter-change", "Oil & filter change", "Servicing",
        "Fresh engine oil to your manufacturer's spec and a new oil filter.",
        45, 6900, None, "general", "instant",
    ),
    DemoService(
        "interim-service", "Interim service", "Servicing",
        "Oil and filter change plus a 30-point safety check, ideal every 6 months.",
        90, 12900, None, "general", "instant",
    ),
    DemoService(
        "full-service", "Full service", "Servicing",
        "Oil, filters, fluids and a 50-point check, recommended every year.",
        180, 21900, None, "general", "instant",
    ),
    DemoService(
        "air-con-regas", "Air-con regas", "Servicing",
        "Recharge your air conditioning and check the system for leaks.",
        60, 7900, None, "general", "instant",
    ),
    DemoService(
        "front-brake-pads", "Front brake pads", "Brakes",
        "Supply and fit new front pads; price depends on your car.",
        90, 12000, 18000, "general", "instant",
    ),
    DemoService(
        "battery-replacement", "Battery replacement", "Electrical",
        "Test, supply and fit a new battery; price depends on battery size.",
        30, 9000, 18000, "general", "instant",
    ),
    DemoService(
        "diagnostic-check", "Diagnostic check", "Diagnostics",
        "Warning light on or something not right? We'll find the cause and quote the fix.",
        60, 6000, None, "general", "needs_approval",
    ),
    DemoService(
        "timing-belt", "Timing belt", "Repairs",
        "Replace the timing belt kit and water pump at your manufacturer's interval.",
        300, 35000, 55000, "general", "needs_approval",
    ),
    DemoService(
        "clutch-replacement", "Clutch replacement", "Repairs",
        "Supply and fit a new clutch kit; we confirm the price after inspection.",
        360, 45000, 75000, "general", "needs_approval",
    ),
]  # fmt: skip

# weekday (0 = Monday) -> (open, close) in garage-local time, or None when closed
DEMO_OPENING_HOURS: Final[dict[int, tuple[time, time] | None]] = {
    0: (time(8, 0), time(17, 30)),
    1: (time(8, 0), time(17, 30)),
    2: (time(8, 0), time(17, 30)),
    3: (time(8, 0), time(17, 30)),
    4: (time(8, 0), time(17, 30)),
    5: (time(9, 0), time(14, 0)),
    6: (time(10, 0), time(13, 0)),
}

# weekday -> breaks; days not listed have none
DEMO_BREAKS: Final[dict[int, list[tuple[time, time]]]] = {
    weekday: [(time(12, 30), time(13, 0))] for weekday in range(5)
}
