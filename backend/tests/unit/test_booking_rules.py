"""The customer-details rules, booking references and hold tokens."""

import pytest

from app.bookings.rules import (
    REFERENCE_ALPHABET,
    clean_email,
    clean_make_or_model,
    clean_name,
    clean_notes,
    clean_phone,
    clean_registration,
    hash_token,
    new_hold_token,
    new_reference,
    token_matches,
)

# --- name ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["A", "x" * 100])
def test_name_lengths_accepted_and_trimmed(value: str) -> None:
    assert clean_name(f"  {value} ") == value


@pytest.mark.parametrize("value", ["", "   ", "x" * 101])
def test_name_lengths_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        clean_name(value)


# --- phone -----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["07700 900123", "+44 (0)7700-900123", "1234567"])
def test_phone_accepted(value: str) -> None:
    assert clean_phone(value) == value


@pytest.mark.parametrize(
    "value",
    ["123456", "07700 90012x", "1" * 21, "+++ ++++ +++", ""],
    ids=["six-digits", "letter", "too-long", "no-digits", "empty"],
)
def test_phone_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        clean_phone(value)


# --- email -----------------------------------------------------------------------


def test_email_is_trimmed_and_lower_cased() -> None:
    assert clean_email(" Sam@Example.COM ") == "sam@example.com"


@pytest.mark.parametrize(
    "value",
    [
        "sam",
        "sam@example",
        "a@@b.com",
        "s am@example.com",
        "@example.com",
        "a@" + "b" * 250 + ".com",
    ],
    ids=["no-at", "no-dot", "two-ats", "space", "nothing-before-at", "too-long"],
)
def test_email_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        clean_email(value)


# --- registration ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), [(" ab12 cde ", "AB12CDE"), ("x1", "X1"), ("abcd1234", "ABCD1234")]
)
def test_registration_normalised(value: str, expected: str) -> None:
    assert clean_registration(value) == expected


@pytest.mark.parametrize("value", ["A", "ABCDEFGH9", "AB-12", ""])
def test_registration_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        clean_registration(value)


# --- make, model, notes ----------------------------------------------------------


def test_make_or_model_limits() -> None:
    assert clean_make_or_model(" Ford ") == "Ford"
    assert clean_make_or_model("x" * 50) == "x" * 50
    for bad in ["", "  ", "x" * 51]:
        with pytest.raises(ValueError):
            clean_make_or_model(bad)


def test_empty_notes_become_none() -> None:
    assert clean_notes("  ") is None
    assert clean_notes(None) is None
    assert clean_notes(" Rattle on the left ") == "Rattle on the left"


def test_notes_over_1000_rejected() -> None:
    assert clean_notes("x" * 1000) == "x" * 1000
    with pytest.raises(ValueError):
        clean_notes("x" * 1001)


# --- references and tokens -------------------------------------------------------


def test_reference_shape() -> None:
    for _ in range(50):
        reference = new_reference()
        assert len(reference) == 9
        assert reference[4] == "-"
        assert set(reference.replace("-", "")) <= set(REFERENCE_ALPHABET)


def test_reference_alphabet_has_no_lookalikes() -> None:
    assert set(REFERENCE_ALPHABET).isdisjoint("01ILO")


def test_token_matches_only_its_hash() -> None:
    token = new_hold_token()
    assert len(token) >= 40
    stored = hash_token(token)
    assert stored != token
    assert len(stored) == 64
    assert token_matches(token, stored)
    assert not token_matches(token + "x", stored)
    assert not token_matches(token, None)


def test_tokens_are_different_each_time() -> None:
    assert new_hold_token() != new_hold_token()
