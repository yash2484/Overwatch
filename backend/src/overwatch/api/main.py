from fastapi import FastAPI

app = FastAPI(title="Overwatch API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
