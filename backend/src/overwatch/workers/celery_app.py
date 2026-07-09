from celery import Celery
from celery.schedules import crontab

from overwatch.config import settings

celery_app = Celery("overwatch", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "UTC"
celery_app.conf.imports = ("overwatch.workers.tasks",)
celery_app.conf.beat_schedule = {
    "enqueue-due-rechecks": {
        "task": "overwatch.enqueue_due_rechecks",
        "schedule": crontab(hour=3, minute=0),  # daily tick; per-AOI cadence_days decides
    },
}


@celery_app.task(name="overwatch.ping")
def ping() -> str:
    return "pong"
