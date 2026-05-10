from fastapi import FastAPI

app = FastAPI(
    title="Mountain WindNinja API",
    description="High-resolution wind forecasting powered by WindNinja",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
