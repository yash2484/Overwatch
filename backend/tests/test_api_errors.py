"""Structured error envelope: ApiError and validation errors share one shape."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from overwatch.api.errors import ApiError, install_error_handlers


def _probe_app() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.get("/boom")
    def boom() -> None:
        raise ApiError(422, "aoi_too_large", "too big", {"area_km2": 1234.5})

    @app.post("/typed")
    def typed(body: Body) -> dict[str, int]:
        return {"n": body.n}

    return TestClient(app)


def test_api_error_envelope() -> None:
    resp = _probe_app().get("/boom")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": {"code": "aoi_too_large", "message": "too big", "detail": {"area_km2": 1234.5}}
    }


def test_validation_error_is_wrapped() -> None:
    resp = _probe_app().post("/typed", json={"n": "not-an-int"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["detail"], list)
