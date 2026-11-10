from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


def make_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards. Tests override it."""
    engine: Engine = request.app.state.engine
    with Session(engine) as session:
        yield session
