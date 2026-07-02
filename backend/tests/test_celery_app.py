from overwatch.workers.celery_app import ping


def test_ping_task_runs_synchronously() -> None:
    assert ping.run() == "pong"
