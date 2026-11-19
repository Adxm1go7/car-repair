"""Slugs are made once from a name: lowercase, dashes, at most 64 characters, unique."""

from app.settings.slugs import make_slug


def test_slug_from_name() -> None:
    assert make_slug("MOT test", set()) == "mot-test"
    assert make_slug("  Brakes & Discs (front)!  ", set()) == "brakes-discs-front"
    assert make_slug("***", set()) == "item"


def test_slug_collision_gets_a_number() -> None:
    assert make_slug("MOT test", {"mot-test"}) == "mot-test-2"
    assert make_slug("MOT test", {"mot-test", "mot-test-2"}) == "mot-test-3"
    assert make_slug("***", {"item"}) == "item-2"


def test_slug_trimmed_to_64() -> None:
    slug = make_slug("a" * 70, set())
    assert slug == "a" * 64
    numbered = make_slug("a" * 70, {"a" * 64})
    assert numbered == "a" * 62 + "-2"
    # Cutting never leaves a dash on the end.
    assert make_slug("a" * 63 + " b", set()) == "a" * 63
