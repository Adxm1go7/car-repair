"""Admins add, edit, hide or show, and reorder services."""

from datetime import timedelta
from typing import Any

from factories import make_hold
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import AuditEntry, BayType, BookingItem, Service
from app.seed import seed

URL = "/api/staff/settings/services"


def general_bay_type(session: Session) -> int:
    return session.scalars(select(BayType.id).where(BayType.slug == "general")).one()


def new_service(session: Session, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Wheel alignment",
        "category": "Tyres",
        "description": "We set the angles of all four wheels so the car tracks straight.",
        "duration_minutes": 60,
        "price_from_pence": 5900,
        "price_to_pence": None,
        "bay_type_id": general_bay_type(session),
        "approval_mode": "instant",
    }
    return body | changes


def add(client: TestClient, session: Session, **changes: Any) -> dict[str, Any]:
    response = client.post(URL, json=new_service(session, **changes))
    assert response.status_code == 201, response.json()
    result: dict[str, Any] = response.json()
    return result


def by_slug(session: Session, slug: str) -> Service:
    return session.scalars(select(Service).where(Service.slug == slug)).one()


def public_slugs(client: TestClient) -> list[str]:
    return [service["slug"] for service in client.get("/api/services").json()]


def audit_actions(session: Session) -> list[str]:
    return list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


def test_add_service_goes_last_and_shows_publicly(
    admin_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    created = add(admin_client, db_session)
    assert created["slug"] == "wheel-alignment"
    assert created["active"] is True
    assert created["bay_type"] == "General bay"
    listed = admin_client.get(URL).json()
    assert listed[-1]["slug"] == "wheel-alignment"
    assert public_slugs(admin_client)[-1] == "wheel-alignment"


def test_add_needs_approval_service(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    created = add(admin_client, db_session, approval_mode="needs_approval")
    assert created["approval_mode"] == "needs_approval"
    assert by_slug(db_session, "wheel-alignment").approval_mode == "needs_approval"


def test_duplicate_name_is_409(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    response = admin_client.post(URL, json=new_service(db_session, name="  mot TEST "))
    assert response.status_code == 409
    assert response.json() == {"detail": "That name is already used"}
    other = add(admin_client, db_session)
    renamed = admin_client.patch(f"{URL}/{other['id']}", json={"name": "MOT Test"})
    assert renamed.status_code == 409
    assert audit_actions(db_session) == ["service.create"]


def test_duration_must_be_15_minute_steps(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    for minutes in (50, 495, 0):
        body = new_service(db_session, duration_minutes=minutes)
        assert admin_client.post(URL, json=body).status_code == 422, minutes
    assert add(admin_client, db_session, duration_minutes=480)["duration_minutes"] == 480


def test_other_bad_fields_are_422(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    bad: list[dict[str, Any]] = [
        {"name": " "},
        {"name": "x" * 101},
        {"category": ""},
        {"description": "x" * 501},
        {"price_from_pence": -1},
        {"price_from_pence": 5000, "price_to_pence": 4000},
        {"approval_mode": "sometimes"},
        {"bay_type_id": 999_999},
    ]
    for changes in bad:
        body = new_service(db_session, **changes)
        assert admin_client.post(URL, json=body).status_code == 422, changes
    service = by_slug(db_session, "mot-test")
    too_low = {"price_to_pence": service.price_from_pence - 1}
    assert admin_client.patch(f"{URL}/{service.id}", json=too_low).status_code == 422
    assert admin_client.patch(f"{URL}/{service.id}", json={"name": None}).status_code == 422


def test_patch_leaves_out_fields_alone(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    created = add(admin_client, db_session, price_to_pence=7900)
    response = admin_client.patch(f"{URL}/{created['id']}", json={"name": "Four-wheel alignment"})
    assert response.status_code == 200
    assert response.json() == created | {"name": "Four-wheel alignment"}


def test_patch_price_to_null_clears_it(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    created = add(admin_client, db_session, price_to_pence=7900)
    response = admin_client.patch(f"{URL}/{created['id']}", json={"price_to_pence": None})
    assert response.json()["price_to_pence"] is None
    assert by_slug(db_session, "wheel-alignment").price_to_pence is None


def test_patch_cannot_change_bay_type_or_approval_mode(
    admin_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    service = by_slug(db_session, "mot-test")
    for body in [
        {"bay_type_id": general_bay_type(db_session)},
        {"approval_mode": "needs_approval"},
        {"slug": "something-else"},
    ]:
        assert admin_client.patch(f"{URL}/{service.id}", json=body).status_code == 422, body


def test_unknown_service_is_404(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    assert admin_client.patch(f"{URL}/999999", json={"active": False}).status_code == 404
    response = admin_client.post(f"{URL}/999999/move", json={"direction": "up"})
    assert response.status_code == 404


def test_hide_and_show(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    service = by_slug(db_session, "mot-test")
    start = utc_now() + timedelta(days=3)
    booking = make_hold(db_session, start, start, status="confirmed")
    hidden = admin_client.patch(f"{URL}/{service.id}", json={"active": False})
    assert hidden.json()["active"] is False
    assert "mot-test" not in public_slugs(admin_client)
    assert "mot-test" in [s["slug"] for s in admin_client.get(URL).json()]
    db_session.refresh(booking)
    assert booking.status == "confirmed"
    admin_client.patch(f"{URL}/{service.id}", json={"active": True})
    assert "mot-test" in public_slugs(admin_client)
    assert audit_actions(db_session) == ["service.hide", "service.show"]


def test_move_swaps_neighbours(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    before = [s["slug"] for s in admin_client.get(URL).json()]
    second = by_slug(db_session, before[1])
    response = admin_client.post(f"{URL}/{second.id}/move", json={"direction": "up"})
    assert response.status_code == 200
    after = [s["slug"] for s in response.json()]
    assert after == [before[1], before[0], *before[2:]]
    down = admin_client.post(f"{URL}/{second.id}/move", json={"direction": "down"})
    assert [s["slug"] for s in down.json()] == before
    assert public_slugs(admin_client) == before
    assert audit_actions(db_session) == ["service.move", "service.move"]


def test_move_at_the_end_is_a_no_op(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    before = [s["slug"] for s in admin_client.get(URL).json()]
    first, last = by_slug(db_session, before[0]), by_slug(db_session, before[-1])
    up = admin_client.post(f"{URL}/{first.id}/move", json={"direction": "up"})
    down = admin_client.post(f"{URL}/{last.id}/move", json={"direction": "down"})
    assert up.status_code == down.status_code == 200
    assert [s["slug"] for s in down.json()] == before
    assert audit_actions(db_session) == []
    bad = admin_client.post(f"{URL}/{first.id}/move", json={"direction": "left"})
    assert bad.status_code == 422


def test_editing_price_leaves_existing_booking_items(
    admin_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    service = by_slug(db_session, "mot-test")
    start = utc_now() + timedelta(days=3)
    booking = make_hold(db_session, start, start, status="confirmed")
    item = BookingItem(
        booking_id=booking.id,
        service_id=service.id,
        service_name=service.name,
        price_from_pence=service.price_from_pence,
        price_to_pence=service.price_to_pence,
        duration_minutes=service.duration_minutes,
        position=0,
    )
    db_session.add(item)
    db_session.flush()
    old = (item.service_name, item.price_from_pence, item.duration_minutes)
    response = admin_client.patch(
        f"{URL}/{service.id}",
        json={"name": "MOT", "price_from_pence": 9999, "duration_minutes": 90},
    )
    assert response.status_code == 200
    db_session.refresh(item)
    assert (item.service_name, item.price_from_pence, item.duration_minutes) == old


def test_each_change_is_audited(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    created = add(admin_client, db_session)
    service_id = created["id"]
    admin_client.patch(f"{URL}/{service_id}", json={"price_from_pence": 6900})
    admin_client.patch(f"{URL}/{service_id}", json={"price_from_pence": 6900})  # no change
    admin_client.patch(f"{URL}/{service_id}", json={"active": False})
    admin_client.post(f"{URL}/{service_id}/move", json={"direction": "up"})
    entries = list(db_session.scalars(select(AuditEntry).order_by(AuditEntry.id)))
    assert [e.action for e in entries] == [
        "service.create",
        "service.update",
        "service.hide",
        "service.move",
    ]
    assert all(e.entity_type == "service" and e.entity_id == service_id for e in entries)
    create, update, hide, move = entries
    assert create.before is None
    assert create.after is not None and create.after["name"] == "Wheel alignment"
    assert update.before == {"price_from_pence": 5900}
    assert update.after == {"price_from_pence": 6900}
    assert (hide.before, hide.after) == ({"active": True}, {"active": False})
    assert move.before is not None and move.after is not None
    assert move.after["position"] == move.before["position"] - 1
