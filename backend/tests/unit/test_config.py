import pytest
from pydantic import ValidationError

from app.config import AppConfig


def test_config_reads_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    config = AppConfig()
    assert config.database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert config.environment == "development"


def test_config_without_database_url_fails_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        AppConfig()


def test_config_rejects_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(ValidationError):
        AppConfig()


def test_worker_interval_defaults_to_60(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.delenv("WORKER_INTERVAL_SECONDS", raising=False)
    assert AppConfig().worker_interval_seconds == 60


def test_worker_interval_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("WORKER_INTERVAL_SECONDS", "5")
    assert AppConfig().worker_interval_seconds == 5


def test_worker_interval_below_1_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("WORKER_INTERVAL_SECONDS", "0")
    with pytest.raises(ValidationError, match="worker_interval_seconds"):
        AppConfig()


URL = "postgresql+psycopg://u:p@h:5432/d"
FAKE_SECRET = "sk_test_x"  # noqa: S105 - not a real key


def clear_stripe(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def test_provider_is_demo_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_stripe(monkeypatch)
    assert AppConfig(database_url=URL).payment_provider == "demo"


def test_provider_is_stripe_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_stripe(monkeypatch)
    config = AppConfig(
        database_url=URL, stripe_secret_key=FAKE_SECRET, stripe_publishable_key="pk_test_x"
    )
    assert config.payment_provider == "stripe"


def test_production_without_a_stripe_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_stripe(monkeypatch)
    with pytest.raises(ValidationError, match="STRIPE_SECRET_KEY"):
        AppConfig(database_url=URL, environment="production")


def test_stripe_key_needs_publishable_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_stripe(monkeypatch)
    with pytest.raises(ValidationError, match="STRIPE_PUBLISHABLE_KEY"):
        AppConfig(database_url=URL, stripe_secret_key=FAKE_SECRET)
