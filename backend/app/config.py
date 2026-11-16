from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application settings, read from environment variables only."""

    model_config = SettingsConfigDict(env_file=None)

    database_url: str
    environment: Literal["development", "test", "production"] = "development"
    # How often the worker releases expired holds.
    worker_interval_seconds: int = Field(default=60, ge=1)
    # Email: the SMTP server the worker sends through, and how often it looks for due email.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "bookings@example.test"
    email_interval_seconds: int = Field(default=5, ge=1)
    # Where customers open the site: booking links in emails start with this.
    public_base_url: str = "http://localhost:8080"
    # Stripe. With no secret key, payments run in demo mode (never allowed in production).
    stripe_secret_key: str = Field(default="", repr=False)
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = Field(default="", repr=False)

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Where a staff write may come from: the site itself, plus the Vite dev server when
        developing (it proxies /api, but the browser still sends its own origin)."""
        origins = {self.public_base_url.rstrip("/")}
        if self.environment == "development":
            origins.add("http://localhost:5173")
        return frozenset(origins)

    @property
    def payment_provider(self) -> Literal["stripe", "demo"]:
        return "stripe" if self.stripe_secret_key else "demo"

    @model_validator(mode="after")
    def check_stripe_keys(self) -> Self:
        if self.environment == "production" and not self.stripe_secret_key:
            raise ValueError("STRIPE_SECRET_KEY is required in production (no demo payments)")
        if self.stripe_secret_key and not self.stripe_publishable_key:
            raise ValueError("STRIPE_PUBLISHABLE_KEY is required with STRIPE_SECRET_KEY")
        return self


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
