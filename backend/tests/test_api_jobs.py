"""Job submit (202 + dispatch) and polling endpoint."""

import pytest
from fastapi.testclient import TestClient

from overwatch.api import jobs as jobs_module
from overwatch.api.main import app

client = TestClient(app)

AOI = {
    "slug": "t3-api-job",
    "name": "J",
    "vertical": "port",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
    },
}
SUBMIT = {
    "before": {"start": "2024-01-01", "end": "2024-01-31"},
    "after": {"start": "2024-06-01", "end": "2024-06-30"},
}


def test_submit_returns_202_and_dispatches(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(jobs_module, "dispatch_detection_job", dispatched.append)
    assert client.post("/aois", json=AOI).status_code == 201

    resp = client.post("/aois/t3-api-job/jobs", json=SUBMIT)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert dispatched == [job_id]

    polled = client.get(f"/jobs/{job_id}")
    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "queued" and body["aoi_slug"] == "t3-api-job"
    assert body["params"] == SUBMIT and body["attempts"] == 0


def test_submit_unknown_aoi_404(clean_t3: None) -> None:
    resp = client.post("/aois/t3-ghost/jobs", json=SUBMIT)
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "aoi_not_found"


def test_submit_backwards_window_422(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_module, "dispatch_detection_job", lambda _: None)
    client.post("/aois", json=AOI)
    bad = {"before": {"start": "2024-01-31", "end": "2024-01-01"}, "after": SUBMIT["after"]}
    resp = client.post("/aois/t3-api-job/jobs", json=bad)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


def test_poll_unknown_job_404(clean_t3: None) -> None:
    resp = client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "job_not_found"
