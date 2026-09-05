FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv from official binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency definitions and metadata needed by build backend
COPY pyproject.toml uv.lock README.md ./

# Install third-party dependencies first without building the project (leverages Docker cache)
RUN uv sync --no-install-project --no-dev

# Copy application source code and migrations
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Complete installation with project package in editable mode
RUN uv sync --no-dev

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Run Alembic migrations and boot FastAPI via Uvicorn
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
