"""SmtpSender against a real SMTP server: the Mailpit image Compose uses."""

import json
import socket
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from app.email.message import OutgoingEmail
from app.email.sender import EmailUnavailable, SmtpSender

MESSAGE = OutgoingEmail(
    to="sam@example.com",
    subject="Your booking is confirmed — ABCD-EFGH",
    text="Plain words £20",
    html="<p>HTML words £20</p>",
    template="confirmation",
)


@dataclass(frozen=True)
class Mailpit:
    host: str
    smtp_port: int
    api: str

    def get(self, path: str) -> Any:
        with urllib.request.urlopen(f"{self.api}{path}", timeout=5) as response:  # noqa: S310
            return json.load(response)


@pytest.fixture(scope="module")
def mailpit() -> Iterator[Mailpit]:
    container = DockerContainer("axllent/mailpit:v1.21").with_exposed_ports(1025, 8025)
    with container:
        wait_for_logs(container, "accessible via", timeout=30)
        host = container.get_container_host_ip()
        yield Mailpit(
            host=host,
            smtp_port=int(container.get_exposed_port(1025)),
            api=f"http://{host}:{container.get_exposed_port(8025)}/api/v1",
        )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_sends_to_a_real_smtp_server(mailpit: Mailpit) -> None:
    SmtpSender(mailpit.host, mailpit.smtp_port, "bookings@example.test").send(MESSAGE)

    found = mailpit.get("/messages")["messages"]
    assert [m["Subject"] for m in found] == [MESSAGE.subject]
    assert found[0]["From"]["Address"] == "bookings@example.test"
    assert found[0]["To"][0]["Address"] == "sam@example.com"
    body = mailpit.get(f"/message/{found[0]['ID']}")
    assert body["Text"].strip() == "Plain words £20"
    assert "<p>HTML words £20</p>" in body["HTML"]


def test_unreachable_server_raises_email_unavailable() -> None:
    sender = SmtpSender("127.0.0.1", free_port(), "bookings@example.test")
    with pytest.raises(EmailUnavailable):
        sender.send(MESSAGE)
