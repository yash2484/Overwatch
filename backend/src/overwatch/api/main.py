from fastapi import FastAPI

from overwatch.api.errors import install_error_handlers

app = FastAPI(title="Overwatch API")
install_error_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
