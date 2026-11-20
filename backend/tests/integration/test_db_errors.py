"""A failed statement's error must not carry its parameters: they can be a customer's email
or phone, and the error text ends up in the JSON logs (uvicorn's and the worker's)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import make_engine


def test_failed_statement_error_hides_its_parameters(migrated_url: str) -> None:
    engine = make_engine(migrated_url)
    try:
        with engine.connect() as connection, pytest.raises(DBAPIError) as caught:
            connection.execute(
                text("INSERT INTO no_such_table (email) VALUES (:email)"),
                {"email": "sam.private@example.com"},
            )
        assert "sam.private@example.com" not in str(caught.value)
    finally:
        engine.dispose()
