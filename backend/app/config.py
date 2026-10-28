from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application settings, read from environment variables only."""

    model_config = SettingsConfigDict(env_file=None)

    database_url: str
    environment: Literal["development", "test", "production"] = "development"


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
