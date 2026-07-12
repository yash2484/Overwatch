"""Per-vertical fusion presets (Phase 5 design §4.2).

Theme identifiers are LITERAL and VERIFIED against the live GDELT taxonomy
(LOOKUP-GKGTHEMES.TXT) during the 2026-07-12 spike — not invented. Corpus counts in the
comments are from that pull.

Two fields, two different jobs (design §4.1):
  * `themes`   narrow RETRIEVAL — recall control, enforced by GDELT against FULL TEXT.
  * `keywords` are the thematic GATE — precision control, enforced by our pure scorer
    against the TITLE (the only text a DOC 2.0 record exposes).
"""

from pydantic import BaseModel, Field


class FusionPreset(BaseModel):
    vertical: str
    themes: list[str] = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    # Window bounds, anchored on the AFTER scene (design decision 3). Tunable per
    # vertical, never hardcoded at the call site — same discipline as Phase 2's min-areas.
    lead_days: int = 30
    lag_days: int = 14


FUSION_PRESETS: dict[str, FusionPreset] = {
    "port": FusionPreset(
        vertical="port",
        themes=[
            "MARITIME",  # 55.0M
            "NEW_CONSTRUCTION",  # 6.9M
            "WB_1803_TRANSPORT_INFRASTRUCTURE",  # 73.5M
        ],
        keywords=[
            "port",
            "seaport",
            "terminal",
            "berth",
            "shipping",
            "cargo",
            "container",
            "harbour",
            "harbor",
            "vessel",
            "transshipment",
        ],
    ),
    "forest": FusionPreset(
        vertical="forest",
        themes=[
            "ENV_DEFORESTATION",  # 722k
            "ENV_FORESTRY",  # 3.6M
        ],
        keywords=[
            # "deforest" is a STEM: it must fire on "deforester" AND "deforestation",
            # which is exactly how the Mongabay and Rio Times demo articles pass
            # (design §4.4). See normalize.match_stems.
            "deforest",
            "desmatamento",
            "logging",
            "clearing",
            "cleared",
            "forest",
            "rainforest",
            "illegal",
        ],
    ),
    "flood": FusionPreset(
        vertical="flood",
        themes=[
            "NATURAL_DISASTER_FLOOD",  # 6.5M
            "NATURAL_DISASTER_FLOODING",  # 6.2M
            "EVACUATION",  # 12.3M
        ],
        keywords=[
            "flood",
            "inundat",
            "evacuat",
            "deluge",
            "submerged",
            "rainfall",
            "water level",
        ],
    ),
}
