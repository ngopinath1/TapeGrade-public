from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.db.database import initialize
from backend.services.state import seed_demo
from backend.services.state import get_league
from backend.api.routes import router
from backend.api.stats import router as stats_router
from backend.security import LOCAL_ORIGINS, LocalOnlyMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    seed_demo()
    yield


app = FastAPI(title="TapeGrade API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(LOCAL_ORIGINS),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)
app.add_middleware(LocalOnlyMiddleware)
app.include_router(router)
app.include_router(stats_router)
for directory in ("cache", "uploads", "samples"):
    (settings.data_dir / directory).mkdir(parents=True, exist_ok=True)
    # Mount only media directories, never the database or root environment files.
    app.mount(
        "/media/" + directory, StaticFiles(directory=settings.data_dir / directory), name=directory
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "models": "mock" if settings.mock_models else "live",
        "demo_league": get_league().get("is_demo", True),
    }
