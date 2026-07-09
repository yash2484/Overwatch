"""GeoJSON detections endpoint with spatial + attribute filters."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from shapely.geometry import box

from overwatch.api.main import app
from overwatch.db.aois import upsert_aoi
from overwatch.db.detections import replace_detections
from overwatch.db.engine import session_scope
from overwatch.db.jobs import create_job
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta

client = TestClient(app)
AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)


def _seed_one_detection() -> None:
    with session_scope() as session:
        aoi_id = upsert_aoi(
            session, slug="t3-api-det", name="D", vertical="port", geometry=AOI_GEOM
        )
        ids = []
        for stac_id, day in (("t3-ad-before", 10), ("t3-ad-after", 20)):
            meta = SceneMeta(
                stac_id=stac_id,
                collection="sentinel-2-l2a",
                captured_at=datetime(2024, 6, day, tzinfo=UTC),
                cloud_pct=1.0,
                epsg=32643,
                assets={},
            )
            ids.append(upsert_scene(session, meta, "t3-api-det", AOI_GEOM, 1.0))
        job = create_job(session, aoi_id, {})
        replace_detections(
            session,
            aoi_id=aoi_id,
            job_id=job.id,
            before_scene_id=ids[0],
            after_scene_id=ids[1],
            detections=[
                Detection(
                    geometry=box(76.97, 8.36, 76.99, 8.38),
                    epsg=4326,
                    area_m2=20_000.0,
                    change_type=ChangeType.CONSTRUCTION,
                    magnitude=0.5,
                    confidence=0.9,
                    contributing_indices={"ssim_dissim": 0.5},
                )
            ],
        )


def test_feature_collection_with_filters(clean_t3: None) -> None:
    _seed_one_detection()

    everything = client.get("/aois/t3-api-det/detections")
    assert everything.status_code == 200
    body = everything.json()
    assert body["type"] == "FeatureCollection" and len(body["features"]) == 1
    props = body["features"][0]["properties"]
    assert props["change_type"] == "construction" and props["area_m2"] == 20_000.0
    assert body["features"][0]["geometry"]["type"] == "Polygon"

    hit = client.get("/aois/t3-api-det/detections?intersects=76.98,8.37,77.0,8.39")
    assert len(hit.json()["features"]) == 1
    miss = client.get("/aois/t3-api-det/detections?intersects=75.0,7.0,75.1,7.1")
    assert len(miss.json()["features"]) == 0
    assert len(client.get("/aois/t3-api-det/detections?since=2024-07-01").json()["features"]) == 0
    assert (
        len(client.get("/aois/t3-api-det/detections?change_type=flooding").json()["features"]) == 0
    )


def test_bad_intersects_422(clean_t3: None) -> None:
    _seed_one_detection()
    resp = client.get("/aois/t3-api-det/detections?intersects=not-a-geometry")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_intersects"
