# Overwatch

Geospatial change-detection intelligence platform: watch areas of interest via Sentinel-2 imagery, detect meaningful change deterministically, correlate detections with geotagged news (GDELT), and generate evidence-linked intelligence briefs where every claim traces to pixels, dates, or cited articles.

- Scope & strategy: [PROJECT.md](PROJECT.md)
- Design: [design-specs/2026-07-02-overwatch-mvp-design.md](design-specs/2026-07-02-overwatch-mvp-design.md)
- Session state: [PROGRESS.md](PROGRESS.md)

## Quick start (dev)

```bash
docker compose up --build
```

- API health: http://localhost:8000/health
- Frontend: http://localhost:5173
