from fastapi import FastAPI

from app.routers import auth

app = FastAPI(
    title="Datachain API",
    description="Ingest and metadata API for Datachain (Epic 1 scaffold).",
    version="0.1.0",
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for local dev and orchestration."""
    return {"status": "ok"}
