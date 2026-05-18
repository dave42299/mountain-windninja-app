import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings

from .deps import get_db
from .routers import forecast_areas, forecasts

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_directory = settings.data_dir
    for subdirectory in ("elevation", "land_cover", "output", "weather"):
        (data_directory / subdirectory).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Mountain WindNinja API",
    description="High-resolution wind forecasting powered by WindNinja",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(forecast_areas.router)
app.include_router(forecasts.router)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        logger.exception("Health check: database unreachable")
        return {"status": "degraded", "database": "unreachable"}
