from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_jwt_secret
from app.routers import auth


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_jwt_secret()
    yield


app = FastAPI(
    title="Datachain API",
    description="Ingest and metadata API for Datachain (Epic 1 scaffold).",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for local dev and orchestration."""
    return {"status": "ok"}
