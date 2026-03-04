# ---------- Build stage ----------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system deps for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml* requirements*.txt* ./
# Install deps, prefer pyproject.toml, fallback to requirements.txt
RUN pip install --upgrade pip && \
    if [ -f pyproject.toml ]; then pip install --no-cache-dir .; \
    elif [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir \
        fastapi uvicorn[standard] \
        redis[asyncio] asyncpg \
        qdrant-client sqlalchemy \
        pydantic pydantic-settings \
        openai httpx langgraph langchain \
        eval_type_backport; \
    fi

# ---------- Runtime stage ----------
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY app/ ./app/

# .env will be mounted or passed via env_file in docker-compose
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
