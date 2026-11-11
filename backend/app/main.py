from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import availability, catalogue, health
from app.config import AppConfig, get_config
from app.db import make_engine


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or get_config()
    engine = make_engine(config.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="Garage API", lifespan=lifespan)
    app.state.engine = engine
    app.include_router(health.router, prefix="/api")
    app.include_router(catalogue.router, prefix="/api")
    app.include_router(availability.router, prefix="/api")
    return app
