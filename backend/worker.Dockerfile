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

# A dedicated, private worker process: no API server or process supervisor.
CMD ["celery", "--app", "app.workers.celery_app", "worker", "--beat", "--loglevel=INFO"]
