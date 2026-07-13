# Evidentia FastAPI backend — production image.
# Build context is the backend/ directory:  docker build -t evidentia-backend backend/
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# System deps kept minimal; psycopg2-binary ships its own libs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Application code (app/, migrations/, alembic.ini, etc.).
COPY . .

EXPOSE 8000

# Container-level healthcheck hits the app's own /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Honor the platform-provided $PORT (Render/Fly/Railway) with a sane default.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
