# ---------- Build stage ----------
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for compiling C extensions (asyncpg, hiredis, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install directly from declared deps (avoids wheel-build issues)
# Copy manifests first for better layer caching
COPY pyproject.toml README.md ./

# Extract and install all runtime deps from pyproject.toml
# We use pip's ability to parse the dependencies list directly
RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
        "fastapi>=0.115.0" \
        "uvicorn[standard]>=0.30.0" \
        "websockets>=13.0" \
        "pydantic>=2.9.0" \
        "pydantic-settings>=2.5.0" \
        "langgraph>=0.2.0" \
        "langchain>=0.3.0" \
        "langchain-core>=0.3.0" \
        "openai>=1.50.0" \
        "google-genai>=1.0.0" \
        "httpx>=0.27.0" \
        "sqlalchemy[asyncio]>=2.0.30" \
        "asyncpg>=0.30.0" \
        "sqlmodel>=0.0.16" \
        "redis[hiredis]>=5.0.0" \
        "qdrant-client>=1.11.0" \
        "python-jose[cryptography]>=3.3.0" \
        "passlib[bcrypt]>=1.7.4" \
        "python-dotenv>=1.0.0" \
        "eval_type_backport"

# ---------- Runtime stage ----------
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source only (not the entire repo)
COPY app/ ./app/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
