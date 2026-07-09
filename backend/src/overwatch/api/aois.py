"""AOI CRUD (design doc §3). The 500 km² cap is enforced here, from Settings."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from geoalchemy2.shape import to_shape
from shapely.geometry import Polygon, mapping, shape
from sqlalchemy.orm import Session

from overwatch.api.deps import get_session
from overwatch.api.errors import ApiError
from overwatch.api.schemas import AoiCreate, AoiOut
from overwatch.config import settings
from overwatch.db.aois import delete_aoi, get_aoi, list_aois, upsert_aoi
from overwatch.db.models import Aoi
from overwatch.geodesy import geodesic_area_km2

router = APIRouter(prefix="/aois", tags=["aois"])

SessionDep = Annotated[Session, Depends(get_session)]


def parse_polygon(geojson: dict[str, Any]) -> Polygon:
    try:
        geom = shape(geojson)
    except Exception as exc:
        raise ApiError(422, "invalid_geometry", f"unparseable GeoJSON: {exc}") from exc
    if not isinstance(geom, Polygon) or not geom.is_valid:
        raise ApiError(422, "invalid_geometry", "geometry must be a valid GeoJSON Polygon")
    return geom


def _to_out(row: Aoi) -> AoiOut:
    geom = to_shape(row.geom)
    return AoiOut(
        slug=row.slug,
        name=row.name,
        vertical=row.vertical,
        geometry=mapping(geom),
        cadence_days=row.cadence_days,
        area_km2=geodesic_area_km2(geom),
        created_at=row.created_at,
    )


def require_aoi(session: Session, slug: str) -> Aoi:
    row = get_aoi(session, slug)
    if row is None:
        raise ApiError(404, "aoi_not_found", f"no AOI with slug {slug!r}")
    return row


@router.post("", status_code=201, response_model=AoiOut)
def create_aoi(payload: AoiCreate, session: SessionDep) -> AoiOut:
    geom = parse_polygon(payload.geometry)
    area = geodesic_area_km2(geom)
    if area > settings.max_aoi_km2:
        raise ApiError(
            422,
            "aoi_too_large",
            f"AOI area {area:.1f} km² exceeds the {settings.max_aoi_km2:.0f} km² cap",
            {"area_km2": area, "max_km2": settings.max_aoi_km2},
        )
    if get_aoi(session, payload.slug) is not None:
        raise ApiError(409, "aoi_exists", f"AOI {payload.slug!r} already exists")
    upsert_aoi(
        session,
        slug=payload.slug,
        name=payload.name,
        vertical=payload.vertical,
        geometry=geom,
        cadence_days=payload.cadence_days,
    )
    return _to_out(require_aoi(session, payload.slug))


@router.get("", response_model=list[AoiOut])
def get_aois(session: SessionDep) -> list[AoiOut]:
    return [_to_out(row) for row in list_aois(session)]


@router.get("/{slug}", response_model=AoiOut)
def get_one(slug: str, session: SessionDep) -> AoiOut:
    return _to_out(require_aoi(session, slug))


@router.delete("/{slug}", status_code=204)
def delete_one(slug: str, session: SessionDep) -> None:
    require_aoi(session, slug)
    delete_aoi(session, slug)
