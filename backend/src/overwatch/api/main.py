from fastapi import FastAPI

from overwatch.api import aois, briefs, detections, fusion, jobs, scenes
from overwatch.api.errors import install_error_handlers

app = FastAPI(title="Overwatch API")
install_error_handlers(app)
app.include_router(aois.router)
app.include_router(jobs.router)
app.include_router(detections.router)
app.include_router(briefs.router)
app.include_router(fusion.router)
app.include_router(scenes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
