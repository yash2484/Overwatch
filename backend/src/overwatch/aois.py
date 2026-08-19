"""Hardcoded showcase AOIs (design spec §5). Seed boxes — refined during Phase 1 eyeballing.

Forest (novo-progresso) was removed from the showcase after the 2026-08-19 closure: it is a
research extension, not a demonstrated capability, and the demo console serves only the
demonstrated verticals (port, flood). The forest detector/fusion/brief code paths remain in the
repo as extension work."""

from pydantic import BaseModel
from shapely.geometry import Polygon, box


class AOI(BaseModel):
    slug: str
    name: str
    vertical: str  # "port" | "forest" | "flood"
    bbox: tuple[float, float, float, float]  # west, south, east, north (EPSG:4326)
    # Toponym-gate inputs (Phase 5 design §4.1). place_terms[0] is the STRICT term GDELT
    # matches against the article's FULL TEXT at retrieval. region_terms are corroboration
    # ONLY — they never enter the GDELT query; they exist because DOC 2.0 exposes only the
    # title, and titles routinely omit the specific place (design §2.5).
    place_terms: list[str] = []
    region_terms: list[str] = []

    def geometry(self) -> Polygon:
        return box(*self.bbox)


# Presentation order for the console, deliberately NOT the seed order or alphabetical.
# The frontend takes `aois[0]` as its default selection and renders the nav in list order,
# so this single sequence decides what a visitor sees first. Porto Alegre leads: the flood
# is the most legible change to a viewer who has never read a satellite image — a city
# turning to water needs no explanation, where a port build-out rewards a second look.
DEMO_ORDER: tuple[str, ...] = ("porto-alegre", "vizhinjam")

SHOWCASE_AOIS: dict[str, AOI] = {
    aoi.slug: aoi
    for aoi in [
        AOI(
            slug="vizhinjam",
            name="Vizhinjam International Seaport, Kerala",
            vertical="port",
            bbox=(76.960, 8.355, 77.010, 8.395),
            # "Vizhinjam" is globally unambiguous and DOES appear in the real headlines.
            place_terms=["Vizhinjam"],
            region_terms=["Thiruvananthapuram", "Kerala"],
        ),
        AOI(
            slug="porto-alegre",
            name="Porto Alegre / Guaiba, Rio Grande do Sul",
            vertical="flood",
            bbox=(-51.300, -30.080, -51.180, -29.980),
            # "Porto Alegre" is an ambiguous toponym (there is one in Portugal), and the
            # real headlines say "Rio Grande do Sul" rather than the city.
            place_terms=["Porto Alegre"],
            region_terms=["Rio Grande do Sul", "Guaiba", "Guaíba"],
        ),
    ]
}
