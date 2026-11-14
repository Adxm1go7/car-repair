import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fakes import FakeProvider
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from app.config import AppConfig
from app.db import get_session, make_engine
from app.main import create_app
from app.payments.deps import get_payment_provider

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    # configparser treats % as interpolation, so escape it in the URL.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:17-alpine") as container:
        yield container.get_connection_url(driver="psycopg")


@pytest.fixture
def fresh_database_url(postgres_url: str) -> Iterator[str]:
    name = f"test_{uuid.uuid4().hex}"
    admin = make_engine(postgres_url)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    yield make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def migrated_url(postgres_url: str) -> str:
    command.upgrade(alembic_config(postgres_url), "head")
    return postgres_url


@pytest.fixture
def db_session(migrated_url: str) -> Iterator[Session]:
    engine = make_engine(migrated_url)
    connection = engine.connect()
    transaction = connection.begin()
    # Commits inside a test become savepoints, so the outer rollback undoes everything.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def client(postgres_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(AppConfig(database_url=postgres_url))) as client:
        yield client


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def api_client(
    db_session: Session, migrated_url: str, fake_provider: FakeProvider
) -> Iterator[TestClient]:
    """A client whose routes use the test's db_session, so test data is rolled back afterwards,
    and whose payments go to `fake_provider`."""
    app = create_app(AppConfig(database_url=migrated_url))

    def use_test_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = use_test_session
    app.dependency_overrides[get_payment_provider] = lambda: fake_provider
    with TestClient(app) as client:
        yield client
