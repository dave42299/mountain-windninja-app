from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

from .routers import forecast_areas, forecasts


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
async def health() -> dict[str, str]:
    return {"status": "ok"}
