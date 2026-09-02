import os

from celery import Celery

celery_app = Celery(
    "prama_dynamagh",
    broker=os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672//"),
    backend=os.environ.get("REDIS_URL", "redis://redis:6379/3"),
)
celery_app.conf.task_default_queue = "prama-dynamagh"

# Importing registers durable task names with every Worker process.
import app.workers.tasks  # noqa: E402,F401
