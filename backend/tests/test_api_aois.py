"""AOI CRUD: create with cap, structured rejections, list/get/delete."""

from fastapi.testclient import TestClient

from overwatch.api.main import app

client = TestClient(app)

SMALL_GEOM = {  # ~1.2 km^2 near the equator
    "type": "Polygon",
    "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
}
HUGE_GEOM = {  # ~12,300 km^2
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}


def _payload(slug: str, geometry: dict) -> dict:
    return {"slug": slug, "name": "Test AOI", "vertical": "port", "geometry": geometry}


def test_create_get_list_delete_roundtrip(clean_t3: None) -> None:
    created = client.post("/aois", json=_payload("t3-crud", SMALL_GEOM))
    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "t3-crud" and 0 < body["area_km2"] < 2

    assert client.get("/aois/t3-crud").status_code == 200
    assert any(a["slug"] == "t3-crud" for a in client.get("/aois").json())

    assert client.delete("/aois/t3-crud").status_code == 204
    missing = client.get("/aois/t3-crud")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "aoi_not_found"


def test_oversized_aoi_rejected_with_structured_error(clean_t3: None) -> None:
    resp = client.post("/aois", json=_payload("t3-huge", HUGE_GEOM))
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "aoi_too_large"
    assert err["detail"]["max_km2"] == 500.0
    assert err["detail"]["area_km2"] > 500.0


def test_invalid_geometry_rejected(clean_t3: None) -> None:
    resp = client.post("/aois", json=_payload("t3-bowtie", BOWTIE))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_geometry"


def test_duplicate_slug_conflict(clean_t3: None) -> None:
    assert client.post("/aois", json=_payload("t3-dup", SMALL_GEOM)).status_code == 201
    resp = client.post("/aois", json=_payload("t3-dup", SMALL_GEOM))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "aoi_exists"


def test_unknown_vertical_is_validation_error(clean_t3: None) -> None:
    payload = _payload("t3-vert", SMALL_GEOM) | {"vertical": "volcano"}
    resp = client.post("/aois", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
