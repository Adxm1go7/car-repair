"""docker-compose.yml wiring the code depends on but can't see."""

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def service(name: str) -> str:
    """The text of one service's block: from `  name:` to the next two-space key."""
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, f"no {name} service in docker-compose.yml"
    return match.group(1)


def test_api_and_worker_share_the_public_base_url() -> None:
    # The api needs it too: the staff Origin check and the cookie's Secure flag read it.
    line = "PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-http://localhost:8080}"
    assert line in service("api")
    assert line in service("worker")


def test_api_trusts_forwarded_ips_only_from_the_web_proxy() -> None:
    web = re.search(r"ipv4_address: (\S+)", service("web"))
    assert web, "the web proxy needs a fixed address to be trusted"
    assert f"TRUSTED_PROXIES: {web.group(1)}" in service("api")
