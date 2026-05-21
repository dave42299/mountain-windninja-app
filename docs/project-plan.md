# WindNinja Forecast App -- Project Plan

## 1. Project Overview

Build a web application that lets users request high-resolution wind forecasts for mountain terrain by:

- Accepting a location (lat/lon), start time, and duration from a web UI
- Automatically fetching terrain (DEM) and land cover (LCP) data for that location
- Downloading the matching HRRR weather forecast from NOAA
- Running the WindNinja solver in a Docker container
- Displaying job progress and serving output file downloads
- (Future) Rendering results in an interactive 3D terrain + wind visualization

The project adapts and extends the existing CLI-based workflow at [Austfi/mountain_windninja](https://github.com/Austfi/mountain_windninja).

---

## 2. Technology Stack (as implemented)

### Backend

- **Framework:** FastAPI + Uvicorn
- **ORM / migrations:** SQLAlchemy 2.x + Alembic
- **Database:** PostgreSQL 16 (Docker in dev)
- **Settings:** pydantic-settings (`.env`)
- **Terrain:** py3dep (DEM), WindNinja `fetch_dem` in Docker (LCP)
- **Weather:** Herbie for HRRR GRIB2 download from AWS S3; xarray + rasterio for grid conversion
- **Solver:** `docker run --rm` invoking `WindNinja_cli` against the `mountain-windninja:local` image

### Frontend

- **UI:** React 19 + TypeScript 5.7, built with Vite 6
- **Routing:** React Router 7
- **Server state:** TanStack Query 5 (adaptive polling for forecast status)
- **Forms:** React Hook Form + Zod validation
- **Map:** MapLibre GL + react-map-gl (CARTO Positron basemap, no API key required)
- **Component library:** shadcn/ui (Radix primitives) + Tailwind CSS v4
- **Toasts:** sonner

### Infrastructure (local dev)

- `docker-compose.yml` runs PostgreSQL only
- `launch` / `launch-server` / `launch-client` scripts orchestrate local dev
- Frontend proxies `/api/*` to `http://localhost:8000` via Vite config

### Data sources (US only for now)

| Data | Source | Resolution | Access |
|------|--------|-----------|--------|
| Terrain DEM | USGS 3DEP | 10 m | py3dep / National Map API (free) |
| Land cover | LANDFIRE LCP | 30 m | WindNinja `fetch_dem` in Docker |
| Weather | NOAA HRRR | ~3 km | AWS S3 via Herbie (free, no auth) |

---

## 3. Repository Structure

```
mountain-windninja-app/
├── backend/                 # FastAPI server (Python 3.12+)
│   ├── api/                 # main.py + routers (forecasts, forecast_areas)
│   ├── services/            # terrain, weather, solver pipeline
│   ├── models/              # ORM tables, Pydantic schemas, enums
│   ├── alembic/             # DB migrations (2 revisions)
│   ├── tests/               # pytest suite (17 modules)
│   ├── config.py            # pydantic-settings
│   ├── Dockerfile           # production-oriented (not used in local dev)
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/                # React + TypeScript SPA
│   └── src/
│       ├── pages/           # MapPage, DashboardPage, ForecastDetailPage
│       ├── components/      # MapView, ForecastForm, SavedLocations, OutputViewer, etc.
│       ├── api/             # client, forecasts, forecast-areas, types
│       └── hooks/           # use-forecasts, use-forecast-areas (polling)
├── solver/                  # Placeholder Dockerfile + scripts/.gitkeep
├── infra/                   # Terraform stub (main.tf with Phase 4 comments)
├── docs/                    # project goals, plan, phase design reports
├── docker-compose.yml       # PostgreSQL only
├── launch                   # Start Postgres + backend + frontend
├── launch-server            # Migrations + uvicorn
├── launch-client            # npm install + vite dev
├── .env.example
└── README.md
```

Runtime data (gitignored): `backend/data/` with `elevation/`, `land_cover/`, `weather/`, `output/` subdirectories created on API startup.

---

## 4. Completed Work

### Phase 1 -- Local CLI proof-of-concept (complete)

Validated the upstream mountain_windninja workflow on macOS/ARM. Documented in `docs/phase1-local-validation.md`. Key outcomes:

- Confirmed WindNinja + OpenFOAM momentum solver runs inside Docker
- Understood output formats (KMZ, ASCII speed/direction grids)
- Identified solver constraints (thread count vs domain size, mesh cache corruption)
- Established the `mountain-windninja:local` Docker image as the solver target

### Phase 2 -- Backend API and services (complete)

Full design in `docs/phase2-backend-design.md`. Implemented:

**API endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | DB connectivity check |
| `POST` | `/forecast-areas/` | Save a named location bookmark |
| `GET` | `/forecast-areas/` | List saved areas |
| `GET` | `/forecast-areas/{id}` | Get one area |
| `DELETE` | `/forecast-areas/{id}` | Delete area (forecasts keep via SET NULL) |
| `POST` | `/forecasts/` | Create forecast, kicks off background pipeline |
| `GET` | `/forecasts/` | Paginated list with status/area filters |
| `GET` | `/forecasts/{id}` | Single forecast (polling target) |
| `GET` | `/forecasts/{id}/output` | File listing when completed (409 otherwise) |
| `GET` | `/forecasts/{id}/output/{filename}` | Download one output file |

**Background pipeline** (triggered by `POST /forecasts/`):

`queued` → `fetching_terrain` → `fetching_weather` → `running_solver` → `completed` | `failed`

**Services:**

- **Terrain:** DEM tile cache via py3dep, LCP tile cache via Docker subprocess, CONUS bounds validation, 25% bbox padding, ORM-backed tile registry
- **Weather:** HRRR cycle resolution (forecast vs pastcast), Herbie GRIB download, U/V → speed/direction ASCII grid conversion onto the DEM grid
- **Solver:** Per-timestep `.cfg` generation for gridded initialization, `docker run` subprocess with retry, NINJAFOAM mesh cache cleanup on failure
- **Storage:** Stub only (`storage.py` placeholder for Phase 4 cloud storage)

**Database (PostgreSQL + Alembic):**

- `forecast_areas` — saved location bookmarks
- `elevation_tiles` — cached DEM tiles with bbox and file path
- `land_cover_tiles` — cached LCP tiles
- `forecasts` — job records with location, tile FKs, status, settings, timestamps, error messages

**Test suite:** 17 test modules under `backend/tests/` covering API, services, geometry, config generation, and mocked Docker interactions. Integration tests gated behind `RUN_TERRAIN_INTEGRATION` and `RUN_SOLVER_INTEGRATION` env flags.

### Phase 3 -- Frontend UI (complete)

Full design in `docs/phase3-frontend-design.md`. Implemented:

**Pages:**

- `/` — MapPage: interactive MapLibre map with click-to-select location, domain rectangle overlay, forecast form sidebar, saved location markers, recent forecasts list
- `/dashboard` — DashboardPage: paginated forecast history with status filtering
- `/forecasts/:id` — ForecastDetailPage: pipeline step indicator, metadata, mini map, output file listing and download

**Key components:**

- `MapView` — click-to-select lat/lon, domain square overlay, saved location markers
- `ForecastForm` — domain size, start time, duration, model (HRRR/NBM), solver type, wind height
- `SavedLocations` — CRUD for forecast area bookmarks, save-from-map flow
- `ForecastSidebar` — recent forecasts on the map page
- `OutputViewer` — file listing and download links for completed forecasts
- `StepIndicator` — visual pipeline progress
- `ThemeToggle` — light/dark mode with localStorage persistence

**API integration:** TanStack Query with adaptive polling intervals for forecast status updates.

---

## 5. Known Gaps and Deferred Items

These items were scoped for Phases 1-3 but are intentionally deferred or partially implemented:

- **NBM weather model:** API enums and form UI accept NBM, but the weather service rejects non-HRRR requests. Deferred until WindNinja exposes a native pastcast path for NBM or the user opts for an archive-forcing workflow.
- **LCP in solver physics:** LCP tiles are downloaded and cached, but the solver config uses DEM + gridded forcing with a uniform vegetation roughness setting (`solver_vegetation`, default `"trees"`). LCP-driven canopy physics is not wired into the solver config yet.
- **Forecast cancellation:** The `cancelled` status exists in the DB enum but there is no cancel endpoint or UI control.
- **CesiumJS:** The original plan called for CesiumJS in Phase 3 for the map. MapLibre GL was chosen instead as a lighter, API-key-free solution for the 2D map interactions. CesiumJS remains the plan for Phase 5's 3D wind visualization.
- **Frontend tests:** No frontend test suite yet.

---

## 6. Remaining Phases

### Phase 4 -- Cloud deployment and solver orchestration

**Goal:** Move from local-only to cloud-hosted so forecasts can run without a local machine.

- Push the WindNinja Docker image to a container registry (GCR or ECR)
- Set up cloud compute for solver jobs:
  - **GCP path:** Cloud Run Jobs (or Compute Engine spot VMs for heavy runs)
  - **AWS path:** AWS Batch with Fargate or EC2 spot instances
- Set up cloud storage bucket for terrain caches, GRIB inputs, and output archives (implement `storage.py`)
- Set up task queue (Cloud Tasks / SQS) to replace the in-process background task with a durable job queue
- Add a callback mechanism: solver container notifies API on completion
- Write Terraform IaC in `infra/` (currently a stub with Phase 4 comments)
- Deploy the FastAPI backend (Cloud Run / App Runner / ECS)
- Deploy the frontend as a static site (Cloud Storage + CDN, or Vercel/Netlify)

### Phase 5 -- 3D wind visualization

**Goal:** Display completed WindNinja output as animated wind particles over 3D terrain in the browser.

- Parse WindNinja ASCII grid output (speed + direction grids) into a tiled wind-field texture (PNG or binary) on the backend
- Replace or augment the MapLibre 2D map with CesiumJS for 3D terrain rendering
- Integrate `cesium-wind-layer` for GPU-accelerated wind particle rendering
- Add a timeline scrubber for multi-hour forecasts
- Color-code particles by wind speed
- Add elevation profile / cross-section tool
- Overlay additional context: place names, peaks, ridgelines

### Phase 6 -- Recurring forecasts, accounts, and polish

**Goal:** Automate scheduled forecast runs and add multi-user support.

- Set up Cloud Scheduler (GCP) or EventBridge (AWS) to trigger new HRRR runs every 1-6 hours for saved forecast areas
- Add user accounts and authentication
- Add email/push notifications when a forecast completes
- Add forecast comparison view (side-by-side or diff overlay)
- Performance tuning: cache terrain aggressively, pre-tile output for fast loading
- Error handling, monitoring, alerting
- Implement forecast cancellation endpoint and UI

---

## 7. Immediate Next Steps

1. **Decide on cloud provider** — GCP vs AWS for compute, storage, and deployment
2. **Implement `storage.py`** — wire up cloud storage (GCS or S3) for terrain cache, weather inputs, and solver output
3. **Replace background tasks with a durable job queue** — the current in-process `BackgroundTasks` approach does not survive server restarts
4. **Write Terraform in `infra/`** — provision container registry, compute, storage bucket, database, and task queue
5. **Deploy the backend and frontend** — get the app accessible from a URL
6. **Wire LCP into solver config** — use the already-cached LCP tiles for vegetation-aware solver runs instead of uniform roughness
