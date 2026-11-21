import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api import (
    availability,
    catalogue,
    demo_inbox,
    demo_payments,
    enquiries,
    health,
    holds,
    my_booking,
    staff_audit,
    staff_auth,
    staff_blocks,
    staff_bookings,
    staff_enquiries,
    staff_schedule,
    staff_settings,
    staff_team,
    stripe_webhook,
)
from app.config import AppConfig, get_config
from app.db import make_engine
from app.limits import TOO_MANY, TooManyAttempts
from app.logs import RequestLogMiddleware, configure_logging
from app.payments.stripe_provider import StripeProvider

log = logging.getLogger("uvicorn.error")  # JSON like every other logger (app/logs.py)

LOCATION_PARTS = {"body", "query", "path", "header", "cookie"}


def validation_message(error: RequestValidationError) -> str:
    """The first problem as "<field>: <message>", matching the string details routes raise."""
    first = error.errors()[0]
    names = [part for part in first.get("loc", ()) if isinstance(part, str)]
    fields = [part for part in names if part not in LOCATION_PARTS]
    field = fields[-1] if fields else "request"
    message = str(first.get("msg", "Invalid value")).removeprefix("Value error, ")
    return f"{field}: {message}"


async def too_many_attempts_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, TooManyAttempts)  # noqa: S101 - registered only for this type
    return JSONResponse(
        status_code=429,
        content={"detail": TOO_MANY},
        headers={"Retry-After": str(error.retry_after)},
    )


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)  # noqa: S101 - registered only for this type
    return JSONResponse(status_code=422, content={"detail": validation_message(error)})


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or get_config()
    configure_logging()
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
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=config.trusted_proxies)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(TooManyAttempts, too_many_attempts_handler)

    @app.middleware("http")
    async def no_sniffing(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.add_middleware(RequestLogMiddleware)  # added last, so outermost: sees the final status

    app.include_router(health.router, prefix="/api")
    app.include_router(catalogue.router, prefix="/api")
    app.include_router(availability.router, prefix="/api")
    app.include_router(holds.router, prefix="/api")
    app.include_router(my_booking.router, prefix="/api")
    app.include_router(enquiries.router, prefix="/api")
    app.include_router(stripe_webhook.router, prefix="/api")
    app.include_router(staff_auth.public_router, prefix="/api")
    app.include_router(staff_auth.router, prefix="/api")
    app.include_router(staff_team.router, prefix="/api")
    app.include_router(staff_schedule.router, prefix="/api")
    app.include_router(staff_bookings.router, prefix="/api")
    app.include_router(staff_blocks.router, prefix="/api")
    app.include_router(staff_enquiries.router, prefix="/api")
    app.include_router(staff_audit.router, prefix="/api")
    app.include_router(staff_settings.router, prefix="/api")
    if config.demo_site:  # the live demo's shared inbox; nothing is ever sent there
        app.include_router(demo_inbox.router, prefix="/api")
    if config.payment_provider == "demo":  # never with Stripe keys, so never in production
        app.include_router(demo_payments.router, prefix="/api")
    return app
