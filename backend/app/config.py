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
    # Stripe. With no secret key, payments run in demo mode (never allowed in production).
    stripe_secret_key: str = Field(default="", repr=False)
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = Field(default="", repr=False)

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
