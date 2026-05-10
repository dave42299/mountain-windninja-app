from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import forecast_areas, forecasts

app = FastAPI(
    title="Mountain WindNinja API",
    description="High-resolution wind forecasting powered by WindNinja",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(forecast_areas.router)
app.include_router(forecasts.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
