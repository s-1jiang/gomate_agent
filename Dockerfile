FROM python:3.13-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md requirements.runtime.lock ./
COPY app ./app
RUN python -m pip install --prefix=/install -r requirements.runtime.lock \
    && python -m pip install --prefix=/install --no-deps .

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/gomate.db
WORKDIR /app
RUN groupadd --system --gid 10001 gomate \
    && useradd --system --uid 10001 --gid gomate --no-create-home gomate \
    && mkdir -p /app/data && chown gomate:gomate /app/data
COPY --from=builder /install /usr/local
USER gomate
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
