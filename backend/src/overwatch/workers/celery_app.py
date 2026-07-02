from celery import Celery

from overwatch.config import settings

celery_app = Celery("overwatch", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "UTC"


@celery_app.task(name="overwatch.ping")
def ping() -> str:
    return "pong"
