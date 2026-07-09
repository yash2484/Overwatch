"""Idempotent showcase-AOI seeder. Run in-container: python -m overwatch.db.seed"""

import logging

from overwatch.aois import SHOWCASE_AOIS
from overwatch.db.aois import upsert_aoi
from overwatch.db.engine import session_scope

logger = logging.getLogger(__name__)


def seed() -> list[int]:
    """Upsert the three showcase AOIs; returns their stable row ids (sorted by slug)."""
    with session_scope() as session:
        return [
            upsert_aoi(
                session,
                slug=aoi.slug,
                name=aoi.name,
                vertical=aoi.vertical,
                geometry=aoi.geometry(),
            )
            for _, aoi in sorted(SHOWCASE_AOIS.items())
        ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ids = seed()
    print(f"seeded {len(ids)} showcase aois: {ids}")
