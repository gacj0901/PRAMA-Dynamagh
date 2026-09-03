from app.workers.celery_app import celery_app
from celery.worker.consumer.consumer import Consumer
from celery.worker.worker import WorkController


def test_worker_does_not_require_rabbitmq_remote_control_queues():
    assert celery_app.conf.worker_enable_remote_control is False
    assert "celery.worker.consumer.mingle:Mingle" not in Consumer.Blueprint.default_steps
    assert "celery.worker.consumer.gossip:Gossip" not in Consumer.Blueprint.default_steps

    worker = WorkController(
        app=celery_app,
        pool="solo",
        concurrency=1,
        loglevel="INFO",
    )
    mingle_steps = [
        step for name, step in worker.consumer.blueprint.steps.items() if "mingle" in name.lower()
    ]
    assert len(mingle_steps) == 1
    assert mingle_steps[0].enabled is False
