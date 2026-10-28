from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from app.config import AppConfig
from app.main import create_app


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:17-alpine") as container:
        yield container.get_connection_url(driver="psycopg")


@pytest.fixture
def client(postgres_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(AppConfig(database_url=postgres_url))) as client:
        yield client
