import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import availability, catalogue, demo_payments, health, holds, stripe_webhook
from app.config import AppConfig, get_config
from app.db import make_engine
from app.payments.stripe_provider import StripeProvider

# uvicorn configures this logger; one of our own would print nothing under it.
log = logging.getLogger("uvicorn.error")

LOCATION_PARTS = {"body", "query", "path", "header", "cookie"}


def validation_message(error: RequestValidationError) -> str:
    """The first problem as "<field>: <message>", matching the string details routes raise."""
    first = error.errors()[0]
    names = [part for part in first.get("loc", ()) if isinstance(part, str)]
    fields = [part for part in names if part not in LOCATION_PARTS]
    field = fields[-1] if fields else "request"
    message = str(first.get("msg", "Invalid value")).removeprefix("Value error, ")
    return f"{field}: {message}"


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)  # noqa: S101 - registered only for this type
    return JSONResponse(status_code=422, content={"detail": validation_message(error)})


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or get_config()
    engine = make_engine(config.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        log.info("payment provider: %s", config.payment_provider)  # never a key
        yield
        engine.dispose()

    app = FastAPI(title="Garage API", lifespan=lifespan)
    app.state.engine = engine
    app.state.config = config
    # One Stripe client for the app; demo mode builds its provider per request (it needs
    # the request's database session).
    app.state.stripe_provider = (
        StripeProvider(config.stripe_secret_key) if config.payment_provider == "stripe" else None
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(health.router, prefix="/api")
    app.include_router(catalogue.router, prefix="/api")
    app.include_router(availability.router, prefix="/api")
    app.include_router(holds.router, prefix="/api")
    app.include_router(stripe_webhook.router, prefix="/api")
    if config.payment_provider == "demo":  # never with Stripe keys, so never in production
        app.include_router(demo_payments.router, prefix="/api")
    return app
