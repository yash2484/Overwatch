"""Scene metadata + on-demand imagery for the Phase 6 console (design §4).

Follows the suite's self-seeding convention: a module-level TestClient, a `t6-`-prefixed
AOI seeded per test, and the `clean_t3` fixture (which knows the `t6-` prefix) for teardown.
No dependency on a real `vizhinjam` row, so this stays green on CI's fresh database.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from shapely.geometry import box

from overwatch.api.main import app
from overwatch.db.aois import upsert_aoi
from overwatch.db.detections import replace_detections
from overwatch.db.engine import session_scope
from overwatch.db.jobs import create_job, mark_succeeded, set_scene
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta

client = TestClient(app)
AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)
SLUG = "t6-scenes"


def _seed_pair() -> None:
    with session_scope() as session:
        upsert_aoi(session, slug=SLUG, name="Scenes AOI", vertical="port", geometry=AOI_GEOM)
        # after (day 20) seeded before before (day 10) on purpose — the endpoint must sort.
        for stac_id, day, cloud in (("t6-after", 20, 2.5), ("t6-before", 10, 1.0)):
            meta = SceneMeta(
                stac_id=stac_id,
                collection="sentinel-2-l2a",
                captured_at=datetime(2024, 6, day, tzinfo=UTC),
                cloud_pct=cloud,
                epsg=32643,
                assets={},
            )
            upsert_scene(session, meta, SLUG, AOI_GEOM, 1.0)


def test_list_scenes_returns_bounds_for_maplibre(clean_t3: None) -> None:
    _seed_pair()
    r = client.get(f"/aois/{SLUG}/scenes")
    assert r.status_code == 200
    scene = r.json()[0]
    assert {"id", "stac_id", "captured_at", "cloud_pct", "usable_fraction", "bounds"} <= set(scene)
    # bounds are [west, south, east, north] — what a MapLibre image source needs.
    assert scene["bounds"] == [76.90, 8.30, 77.10, 8.50]


def test_scenes_are_ordered_by_capture_date(clean_t3: None) -> None:
    _seed_pair()
    dates = [s["captured_at"] for s in client.get(f"/aois/{SLUG}/scenes").json()]
    assert dates == sorted(dates)
    assert [s["stac_id"] for s in client.get(f"/aois/{SLUG}/scenes").json()] == [
        "t6-before",
        "t6-after",
    ]


def test_scenes_follow_active_detection_pair_when_history_exists(clean_t3: None) -> None:
    with session_scope() as session:
        aoi_id = upsert_aoi(
            session, slug=SLUG, name="Scenes AOI", vertical="port", geometry=AOI_GEOM
        )
        scene_ids = []
        for stac_id, day in (
            ("t6-before", 10),
            ("t6-active-after", 20),
            ("t6-historical-later", 30),
        ):
            meta = SceneMeta(
                stac_id=stac_id,
                collection="sentinel-2-l2a",
                captured_at=datetime(2024, 6, day, tzinfo=UTC),
                cloud_pct=1.0,
                epsg=32643,
                assets={},
            )
            scene_ids.append(upsert_scene(session, meta, SLUG, AOI_GEOM, 1.0))
        job = create_job(session, aoi_id, {})
        set_scene(session, job.id, "before", scene_ids[0])
        set_scene(session, job.id, "after", scene_ids[1])
        replace_detections(
            session,
            aoi_id=aoi_id,
            job_id=job.id,
            before_scene_id=scene_ids[0],
            after_scene_id=scene_ids[1],
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
        mark_succeeded(session, job.id, 1)

    rows = client.get(f"/aois/{SLUG}/scenes").json()
    assert [row["stac_id"] for row in rows] == ["t6-before", "t6-active-after"]


def test_scenes_follow_latest_successful_pair_when_it_has_zero_detections(
    clean_t3: None,
) -> None:
    with session_scope() as session:
        aoi_id = upsert_aoi(
            session, slug=SLUG, name="Scenes AOI", vertical="port", geometry=AOI_GEOM
        )
        scene_ids = []
        for stac_id, day in (
            ("t6-old-before", 10),
            ("t6-old-after", 20),
            ("t6-current-before", 25),
            ("t6-current-after", 30),
        ):
            meta = SceneMeta(
                stac_id=stac_id,
                collection="sentinel-2-l2a",
                captured_at=datetime(2024, 6, day, tzinfo=UTC),
                cloud_pct=1.0,
                epsg=32643,
                assets={},
            )
            scene_ids.append(upsert_scene(session, meta, SLUG, AOI_GEOM, 1.0))

        old_job = create_job(session, aoi_id, {})
        old_job.created_at = datetime(2024, 7, 1, tzinfo=UTC)
        set_scene(session, old_job.id, "before", scene_ids[0])
        set_scene(session, old_job.id, "after", scene_ids[1])
        replace_detections(
            session,
            aoi_id=aoi_id,
            job_id=old_job.id,
            before_scene_id=scene_ids[0],
            after_scene_id=scene_ids[1],
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
        mark_succeeded(session, old_job.id, 1)

        current_job = create_job(session, aoi_id, {})
        current_job.created_at = datetime(2024, 7, 2, tzinfo=UTC)
        set_scene(session, current_job.id, "before", scene_ids[2])
        set_scene(session, current_job.id, "after", scene_ids[3])
        mark_succeeded(session, current_job.id, 0)

    rows = client.get(f"/aois/{SLUG}/scenes").json()
    assert [row["stac_id"] for row in rows] == ["t6-current-before", "t6-current-after"]


def test_unknown_aoi_returns_404(clean_t3: None) -> None:
    r = client.get("/aois/t6-nope/scenes")
    assert r.status_code == 404 and r.json()["error"]["code"] == "aoi_not_found"


def test_image_serves_a_cached_png_without_rerendering(
    clean_t3: None, tmp_path, monkeypatch
) -> None:
    from overwatch.api import scenes as scenes_mod

    monkeypatch.setattr(scenes_mod.settings, "scene_image_dir", tmp_path)
    _seed_pair()
    scene = client.get(f"/aois/{SLUG}/scenes").json()[0]

    called: list[int] = []
    monkeypatch.setattr(scenes_mod, "render_scene_png", lambda *a, **k: called.append(1))
    # Pre-place a cached file on the deterministic path.
    path = scenes_mod.scene_image_path(SLUG, scene["stac_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    r = client.get(f"/scenes/{scene['id']}/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert called == [], "a cached image must not be re-rendered"


def test_image_renders_on_demand_when_missing(clean_t3: None, tmp_path, monkeypatch) -> None:
    from overwatch.api import scenes as scenes_mod

    monkeypatch.setattr(scenes_mod.settings, "scene_image_dir", tmp_path)
    _seed_pair()
    scene = client.get(f"/aois/{SLUG}/scenes").json()[0]

    rendered: list[int] = []

    def fake_render(scene_row, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        rendered.append(scene_row.id)
        return out_path

    monkeypatch.setattr(scenes_mod, "render_scene_png", fake_render)
    assert client.get(f"/scenes/{scene['id']}/image").status_code == 200
    assert rendered == [scene["id"]]


def test_image_render_failure_is_a_structured_503(clean_t3: None, tmp_path, monkeypatch) -> None:
    from overwatch.api import scenes as scenes_mod

    monkeypatch.setattr(scenes_mod.settings, "scene_image_dir", tmp_path)
    _seed_pair()
    scene = client.get(f"/aois/{SLUG}/scenes").json()[0]

    def boom(*a, **k):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(scenes_mod, "render_scene_png", boom)
    r = client.get(f"/scenes/{scene['id']}/image")
    assert r.status_code == 503 and r.json()["error"]["code"] == "scene_render_failed"


def test_unknown_scene_image_returns_404(clean_t3: None) -> None:
    r = client.get("/scenes/999999/image")
    assert r.status_code == 404 and r.json()["error"]["code"] == "scene_not_found"
