FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[test]"
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests ./tests

EXPOSE 8000

# Railway runs migrations before starting the single public API process. The
# worker has its own Dockerfile so it never runs this API command.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
