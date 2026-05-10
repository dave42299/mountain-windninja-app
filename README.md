# Mountain WindNinja App

A web application for creating detailed, high-resolution 3D wind forecasts over complex mountain terrain, powered by [WindNinja](https://research.fs.usda.gov/firelab/products/dataandtools/windninja).

## Overview

This app wraps the WindNinja diagnostic wind model in a user-friendly web interface that:

- Accepts a location (lat/lon), forecast start time, and duration
- Automatically fetches terrain elevation (DEM) and land cover (LCP) data
- Downloads HRRR weather forecast data from NOAA
- Runs the WindNinja solver on cloud compute
- Archives results to cloud storage
- Displays output as an interactive 3D wind visualization over terrain

## Project Structure

```
mountain-windninja-app/
├── backend/          # FastAPI server (Python)
│   ├── api/          # REST endpoint routers
│   ├── services/     # Terrain, weather, solver orchestration
│   └── models/       # DB models and Pydantic schemas
├── frontend/         # React + CesiumJS web UI (TypeScript)
│   └── src/
├── solver/           # WindNinja Docker wrapper
│   ├── scripts/      # Run and fetch scripts
│   └── Dockerfile
├── infra/            # Terraform IaC for cloud resources
├── docs/             # Project documentation
└── docker-compose.yml
```

## Getting Started

See [docs/project-goals.md](docs/project-goals.md) for project background and goals.

### Prerequisites

- Docker
- Python 3.11+
- Node.js 20+
- Terraform (for cloud deployment)

### Local Development

```bash
# Start all services locally
docker compose up

# Backend only
cd backend && pip install -e ".[dev]" && uvicorn api.main:app --reload

# Frontend only
cd frontend && npm install && npm run dev
```

## Acknowledgments

- [WindNinja](https://github.com/firelab/windninja) by USDA Forest Service Fire Lab
- [mountain_windninja](https://github.com/Austfi/mountain_windninja) CLI workflow (reference implementation)
- NOAA HRRR data via [AWS Open Data](https://registry.opendata.aws/noaa-hrrr-pds/)
