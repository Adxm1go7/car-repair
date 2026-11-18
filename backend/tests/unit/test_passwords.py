import pytest

from app.staff.passwords import clean_password, hash_password, password_matches


def test_password_of_7_is_refused_and_8_accepted() -> None:
    with pytest.raises(ValueError, match="at least 8 characters"):
        clean_password("1234567")
    assert clean_password("12345678") == "12345678"


def test_password_over_200_is_refused() -> None:
    with pytest.raises(ValueError, match="at most 200 characters"):
        clean_password("x" * 201)
    assert clean_password("x" * 200) == "x" * 200


def test_password_spaces_are_kept() -> None:
    assert clean_password("  spaced  ") == "  spaced  "


def test_password_matches_after_hash() -> None:
    stored = hash_password("correct horse")
    assert stored != "correct horse"
    assert password_matches("correct horse", stored)
    assert not password_matches("wrong horse", stored)


def test_password_matches_none_is_false() -> None:
    assert not password_matches("anything", None)


def test_password_matches_garbage_hash_is_false() -> None:
    assert not password_matches("anything", "not-a-hash")
