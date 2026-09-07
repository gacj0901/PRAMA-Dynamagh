import os

from celery import Celery
from celery.worker.consumer import mingle as mingle_module
from celery.worker.consumer.consumer import Consumer
from app.redis_config import redis_url


_mingle_init = mingle_module.Mingle.__init__


def _disabled_mingle_init(self, consumer, *args, **kwargs):
    """Apply Celery's --without-mingle behavior to Railway's fixed CLI."""

    kwargs["without_mingle"] = True
    _mingle_init(self, consumer, *args, **kwargs)


mingle_module.Mingle.__init__ = _disabled_mingle_init

celery_app = Celery(
    "prama_dynamagh",
    broker=os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672//"),
    backend=redis_url(),
)
celery_app.conf.task_default_queue = "prama-dynamagh"
celery_app.conf.worker_concurrency = 2
celery_app.conf.worker_prefetch_multiplier = 1
# RabbitMQ 4 disables transient non-exclusive pidbox queues by default.
# PRAMA does not use remote-control commands for any durable workflow, so
# disabling that optional channel preserves broker delivery semantics while
# preventing worker restart loops.
celery_app.conf.worker_enable_remote_control = False
# RabbitMQ 4 also rejects the transient queues used by Celery's optional
# mingle/gossip discovery. PRAMA's durable task queue, scheduling, and
# idempotency controls do not use peer discovery.
Consumer.Blueprint.default_steps = [
    step
    for step in Consumer.Blueprint.default_steps
    if step
    not in {
        "celery.worker.consumer.mingle:Mingle",
        "celery.worker.consumer.gossip:Gossip",
    }
]
celery_app.conf.beat_schedule = {
    # The task is harmless while the global switch is false (the default).
    # Policy cadence/budgets remain the authoritative scheduling controls.
    "autonomy-tick": {"task": "prama.autonomy_tick", "schedule": 60.0},
}

# Importing registers durable task names with every Worker process.
import app.workers.tasks  # noqa: E402,F401
