"""AOI persistence — idempotent upsert on the slug natural key (design doc §2)."""

from datetime import datetime

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from overwatch.db.models import Aoi


def upsert_aoi(
    session: Session,
    *,
    slug: str,
    name: str,
    vertical: str,
    geometry: Polygon,
    cadence_days: int | None = None,
    place_terms: list[str] | None = None,
    region_terms: list[str] | None = None,
) -> int:
    """Insert or update by slug; returns the stable row id.

    Re-seeding refreshes name/vertical/geom and the toponym terms, but never clobbers
    cadence_days or last_checked_at (user-owned scheduling state).
    """
    geom = from_shape(geometry, srid=4326)
    stmt = (
        insert(Aoi)
        .values(
            slug=slug,
            name=name,
            vertical=vertical,
            geom=geom,
            cadence_days=cadence_days,
            place_terms=place_terms,
            region_terms=region_terms,
        )
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={
                "name": name,
                "vertical": vertical,
                "geom": geom,
                "place_terms": place_terms,
                "region_terms": region_terms,
                "updated_at": func.now(),
            },
        )
        .returning(Aoi.id)
    )
    return session.execute(stmt).scalar_one()


def get_aoi(session: Session, slug: str) -> Aoi | None:
    return session.scalar(select(Aoi).where(Aoi.slug == slug))


def list_aois(session: Session) -> list[Aoi]:
    return list(session.scalars(select(Aoi).order_by(Aoi.slug)))


def delete_aoi(session: Session, slug: str) -> bool:
    """Delete by slug; jobs and detections cascade via FK, scenes are kept."""
    return session.execute(delete(Aoi).where(Aoi.slug == slug)).rowcount > 0


def stamp_checked(session: Session, aoi_id: int, when: datetime) -> None:
    session.execute(
        update(Aoi).where(Aoi.id == aoi_id).values(last_checked_at=when, updated_at=func.now())
    )
