# ---------- Build stage ----------
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for compiling C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only the dependency manifest first (for layer caching)
COPY pyproject.toml README.md ./

# Install all runtime dependencies declared in pyproject.toml
RUN pip install --upgrade pip && \
    pip install --no-cache-dir ".[dev]" || pip install --no-cache-dir .

# ---------- Runtime stage ----------
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY app/ ./app/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
