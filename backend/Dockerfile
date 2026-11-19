# Build stage: install dependencies into a virtualenv with uv.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Runtime stage: just Python, the virtualenv and our code.
FROM python:3.13-slim-bookworm
# pip isn't used at runtime, and its bundled libraries (urllib3, msgpack) lag behind their
# security fixes, so leave it out.
RUN useradd --create-home --uid 1000 app && python -m pip uninstall --yes pip
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000"]
