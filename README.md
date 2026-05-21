# Mountain WindNinja App

A web application for creating detailed, high-resolution 3D wind forecasts over complex mountain terrain, powered by [WindNinja](https://research.fs.usda.gov/firelab/products/dataandtools/windninja).

## Overview

This app wraps the WindNinja diagnostic wind model in a web interface that:

- Accepts a location (lat/lon), forecast start time, and duration
- Automatically fetches terrain elevation (DEM) and land cover (LCP) data
- Downloads HRRR weather forecast data from NOAA
- Runs the WindNinja solver in Docker
- Surfaces job status and output file downloads in the browser
- Displays results on a 3D CesiumJS globe with terrain rendering
- Visualizes wind fields as a 3D arrow vector field overlay (speed-colored, direction-aware) with adaptive density, plus an optional animated particle mode

**Current status:** Phase 2 (backend API), Phase 3 (React frontend with CesiumJS 3D map), and Phase 3b (wind visualization with 3D arrow vector field and particle animation) are complete. The app provides an end-to-end workflow from forecast submission through interactive 3D wind visualization. Cloud deployment is planned for a later phase.

## Project Structure

```
mountain-windninja-app/
├── backend/              # FastAPI server (Python 3.12+)
│   ├── api/              # REST endpoint routers
│   ├── services/         # Terrain, weather, solver orchestration
│   └── models/           # DB models and Pydantic schemas
├── frontend/             # React + TypeScript SPA (Vite, CesiumJS)
│   └── src/
├── solver/               # WindNinja Docker wrapper
├── docs/                 # Design reports and project goals
├── docker-compose.yml    # PostgreSQL only (backend runs natively)
├── launch                # Start Postgres + backend + frontend
├── launch-server         # Start backend only
└── launch-client         # Start frontend only
```

## Getting Started

See [docs/project-goals.md](docs/project-goals.md) for background and roadmap. Design reports: [Phase 2 backend](docs/phase2-backend-design.md), [Phase 3 frontend](docs/phase3-frontend-design.md).

### Prerequisites

- **Docker** — PostgreSQL via `docker-compose.yml`; WindNinja solver image for full forecast runs
- **Python 3.12+** — backend API (native, not containerized in dev)
- **Node.js 20+** and **npm** — frontend dev server
- **Cesium Ion account** — free account at [cesium.com/ion](https://cesium.com/ion) for terrain and imagery tiles

### First-time backend setup

From the repo root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example .env   # if .env does not exist
```

`launch-server` and `launch` run `alembic upgrade head` automatically on startup.

### First-time frontend setup

```bash
cd frontend
cp .env.example .env
# Edit .env and paste your Cesium Ion token
```

### Quick start (recommended)

From the repo root:

```bash
./launch
```

This will:

1. Start PostgreSQL in Docker and wait until it is healthy
2. Run database migrations and start the API at http://localhost:8000
3. Install frontend dependencies if needed and start Vite at http://localhost:5173

Press **Ctrl+C** to stop the frontend, backend, and Postgres container.

### Start services individually

```bash
# Terminal 1 — API + migrations (requires Postgres running)
docker compose up -d
./launch-server

# Terminal 2 — frontend
./launch-client
```

| Service    | URL                      |
|------------|--------------------------|
| Frontend   | http://localhost:5173  |
| Backend API| http://localhost:8000  |
| API health | http://localhost:8000/health |
| Postgres   | `localhost:5432` (user/db: `windninja`) |

The frontend proxies `/api/*` to the backend during development (see `frontend/vite.config.ts`).

### Full forecast pipeline (optional)

Submitting forecasts that complete through terrain, weather, and solver stages requires the **mountain-windninja** solver Docker image (see [mountain_windninja](https://github.com/Austfi/mountain_windninja) or this repo's `solver/`). Without it, the UI still works for creating jobs and viewing status; runs may fail during terrain or solver steps depending on your environment.

## Acknowledgments

- [WindNinja](https://github.com/firelab/windninja) by USDA Forest Service Fire Lab
- [mountain_windninja](https://github.com/Austfi/mountain_windninja) CLI workflow (reference implementation)
- NOAA HRRR data via [AWS Open Data](https://registry.opendata.aws/noaa-hrrr-pds/)
- [CesiumJS](https://cesium.com/cesiumjs/) for 3D globe rendering
