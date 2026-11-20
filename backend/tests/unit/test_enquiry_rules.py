"""What an enquiry's description must be."""

import pytest

from app.enquiries.rules import clean_description


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("x" * 10, "x" * 10),
        ("x" * 1000, "x" * 1000),
        ("  " + "x" * 10 + "  ", "x" * 10),
        ("\n" + "y" * 1000 + "\n", "y" * 1000),
    ],
)
def test_description_limits_accept(value: str, expected: str) -> None:
    assert clean_description(value) == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("x" * 9, "Please describe the problem in at least 10 characters"),
        ("  " + "x" * 9 + "  ", "Please describe the problem in at least 10 characters"),
        ("x" * 1001, "The description can be at most 1000 characters"),
        ("   ", "Please describe the problem"),
        ("", "Please describe the problem"),
    ],
)
def test_description_limits(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        clean_description(value)


def test_description_nul_refused() -> None:
    with pytest.raises(ValueError, match="^Please remove unusual characters$"):
        clean_description("Rattle from the\x00 front left")
