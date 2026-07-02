"""Hardcoded showcase AOIs (design spec §5). Seed boxes — refined during Phase 1 eyeballing."""

from pydantic import BaseModel
from shapely.geometry import Polygon, box


class AOI(BaseModel):
    slug: str
    name: str
    vertical: str  # "port" | "forest" | "flood"
    bbox: tuple[float, float, float, float]  # west, south, east, north (EPSG:4326)

    def geometry(self) -> Polygon:
        return box(*self.bbox)


SHOWCASE_AOIS: dict[str, AOI] = {
    aoi.slug: aoi
    for aoi in [
        AOI(
            slug="vizhinjam",
            name="Vizhinjam International Seaport, Kerala",
            vertical="port",
            bbox=(76.960, 8.355, 77.010, 8.395),
        ),
        AOI(
            slug="novo-progresso",
            name="Novo Progresso (BR-163), Para",
            vertical="forest",
            bbox=(-55.450, -7.150, -55.350, -7.050),
        ),
        AOI(
            slug="porto-alegre",
            name="Porto Alegre / Guaiba, Rio Grande do Sul",
            vertical="flood",
            bbox=(-51.300, -30.080, -51.180, -29.980),
        ),
    ]
}
