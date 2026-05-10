# Phase 2: Backend API Design Report

**Date:** May 10, 2026
**Status:** In progress (data model and dev environment complete; services and endpoints pending)

## Objective

Design and build a FastAPI backend that accepts user parameters and automates the terrain fetching, weather download, and WindNinja solver pipeline -- replacing the CLI-based workflow validated in Phase 1 with HTTP API endpoints.

## Scope Assumptions

- **US locations only.** Both primary data sources (USGS 3DEP for elevation, LANDFIRE for land cover) are US-only. International support (SRTM/GMTED) may be added later but is not a Phase 2 design priority.
- **Single-user, local execution.** No authentication, no multi-tenancy. The solver runs in a local Docker container invoked via subprocess. Cloud execution is deferred to Phase 4.
- **HRRR weather model only.** NBM is accepted as a parameter but the weather service implementation focuses on HRRR via AWS S3.

## Key Design Decisions

### 1. Hybrid UX: ephemeral "click and run" + saved locations

Users can initiate a forecast in two ways:

- **Ephemeral:** Click a point on the map, set parameters, run. No saving required. The system finds or downloads terrain, runs the solver, and shows results.
- **Saved:** Optionally save a location as a named ForecastArea (e.g., "Berthoud Pass") for quick reuse, historical comparison, or scheduled recurring forecasts.

This led to the Forecast table storing location parameters (center_latitude, center_longitude, size_km) directly, with an optional foreign key to ForecastArea. Every forecast knows where it was, regardless of whether a saved area exists.

### 2. Separate elevation and land cover caching

DEM (elevation) and LCP (land cover) data are cached in independent tables rather than as columns on a single "domain" row. The reasons:

| Property | DEM (Elevation) | LCP (Land Cover) |
|----------|----------------|-------------------|
| Source | USGS 3DEP | LANDFIRE |
| Format | GeoTIFF, 1 band | LCP, 8 bands (elevation + vegetation + fuel) |
| CRS | UTM (we choose at download) | LANDFIRE native Albers (~EPSG:5070, we don't control) |
| Resolution | 10m | ~30m |
| Update frequency | Almost never | Occasionally (fires, logging, development) |
| Coverage | US (3DEP), global (SRTM) | US only |

Independent tables allow re-downloading land cover after e.g a wildfire without touching the stable elevation data. Each forecast records which specific tiles it used, providing full traceability -- if land cover is updated, new forecasts use the new tile while old forecasts still reference the original.

### 3. Bounding box spatial caching with 25% padding

Terrain tiles are cached by their geographic bounding box (stored in WGS84 decimal degrees). When a user requests a forecast, the system checks whether an existing tile's bounding box fully contains the requested area before downloading new data.

To improve cache hit rates for nearby requests, tile downloads are padded by 25% beyond the user's requested area. A 12 km request downloads ~15 km of terrain. This absorbs the common case where a user clicks slightly differently on a second visit.

The stored bounding box always reflects the actual downloaded file extent (read via GDAL after download), not the original request. This ensures spatial containment queries are accurate.

This "padding" strategy was determined to be sufficient for initial implementation and could be revisited in later development if needed for additional optimization.

### 4. Convention-based output paths

Forecast output directories are derived from the forecast UUID (`data/output/{forecast_id}/`) rather than stored in the database. This avoids path bookkeeping and ensures every forecast has a predictable, unique output location.

### 5. Native backend development, Dockerized Postgres

The FastAPI backend runs natively on the Mac (Python 3.12 via pyenv) for fast iteration. Only Postgres runs in Docker via `docker-compose.yml`. This avoids container restart delays during development while keeping the database reproducible.

## Architectural Tradeoffs Considered

### Terrain table structure

Three options were evaluated:

1. **Combined row** -- DEM path + LCP path as columns on a single domain table. Simple but couples data with different update cadences, loses history on re-download, and conflates two different CRS values in one row.
2. **Separate tables** (chosen) -- `elevation_tiles` and `land_cover_tiles`. Independent lifecycle, clear semantics, full traceability per forecast. Minor duplication in table definitions.
3. **Generic tile table with type column** -- Single table, differentiated by a `type` discriminator. Flexible but adds filtering complexity to every query and nullable columns that only apply to one type.

Option 2 was chosen for clarity and independent lifecycle management.

### "Domain" naming and necessity

The original plan centered on a "Domain" concept (borrowed from WindNinja CLI terminology). Through design review, this evolved:

- "Domain" was renamed to "ForecastArea" for user-facing clarity.
- ForecastArea was made optional (nullable FK on Forecast) to support ephemeral forecasts.
- Location parameters were added directly to Forecast so every forecast is self-describing.

### Tile resolution storage

Resolution columns (`resolution_m`) were initially included on tile tables but removed after analysis showed: (a) resolution is fixed by the data source (10m for 3DEP, ~30m for LANDFIRE), (b) WindNinja reads resolution from the file metadata directly, and (c) no current logic branches on resolution. Comments document the omission rationale for future reference.

### Solver job execution model

Three options were evaluated:

1. **Synchronous** -- API blocks until solver completes. Simple but locks the HTTP connection for 30-60+ seconds.
2. **Background task with status table** (chosen) -- API returns immediately with a forecast ID. A background worker updates status in Postgres. Frontend polls for progress. Swappable to cloud job queue in Phase 4.
3. **Real task queue** (Redis/Celery) -- Production-grade but massive overkill for Phase 2 single-user local execution.

Option 2 provides the right API shape (submit, poll, retrieve) without infrastructure overhead.

## Data Model

Four tables, implemented in `backend/models/orm.py`:

```
ForecastArea (optional saved location)
  id, label, center_latitude, center_longitude, size_km, created_at

ElevationTile (cached DEM files)
  id, bbox_north/south/east/west, crs_epsg, file_path, source, downloaded_at, file_size_bytes

LandCoverTile (cached LCP files)
  id, bbox_north/south/east/west, crs_epsg, file_path, source, downloaded_at, file_size_bytes

Forecast (a single wind forecast job)
  id, forecast_area_id (nullable FK → SET NULL), center_latitude, center_longitude, size_km,
  elevation_tile_id (FK → RESTRICT), land_cover_tile_id (nullable FK → RESTRICT),
  status (enum), weather_model (enum), solver_type (enum), output_wind_height,
  forecast_start, duration_hours,
  error_message, created_at, started_at, completed_at
```

Enums (defined in `backend/models/orm.py`, used by ORM defaults and Pydantic schemas):
- **ForecastStatus:** queued, fetching_weather, running_solver, completed, failed
- **WeatherModel:** hrrr, nbm
- **SolverType:** mass_conservation, momentum

Relationships:
- ForecastArea has many Forecasts (optional grouping; SET NULL on area deletion)
- ElevationTile is referenced by many Forecasts (RESTRICT deletion)
- LandCoverTile is referenced by many Forecasts (nullable for non-US; RESTRICT deletion)

Naming convention:
- `latitude` / `longitude` for user-input single-point coordinates (API create schemas)
- `center_latitude` / `center_longitude` for area/domain center points (ORM, response schemas, ForecastArea)
- `bbox_north/south/east/west` for bounding boxes (tile tables)

File path convention:
- Tile `file_path` values are stored relative to `settings.data_dir` (e.g. `elevation/abc123.tif`). The service layer resolves them to absolute paths at read time.

## API Endpoints (planned)

| Method | Path | Purpose |
|--------|------|---------|
| POST | /forecast-areas | Save a named location |
| GET | /forecast-areas | List saved locations |
| GET | /forecast-areas/{id} | Get a saved location |
| DELETE | /forecast-areas/{id} | Remove a saved location |
| POST | /forecasts | Submit a forecast (from saved area or ad-hoc lat/lon) |
| GET | /forecasts | List forecasts (filter by area, status) |
| GET | /forecasts/{id} | Get forecast status and metadata |
| GET | /forecasts/{id}/output | List output files |
| GET | /forecasts/{id}/output/{filename} | Download an output file |
| GET | /health | Health check |

## Data Flow (Phase 2)

```
User request (lat/lon, size_km, time, duration)
        |
        v
  Compute padded bbox (25% buffer)
        |
        +---> Query elevation_tiles: bbox contains requested area?
        |       |-- Yes: reuse cached tile
        |       |-- No:  download from USGS 3DEP, insert new tile
        |
        +---> Query land_cover_tiles: bbox contains requested area?
        |       |-- Yes: reuse cached tile
        |       |-- No:  download from LANDFIRE, insert new tile
        |
        v
  Insert Forecast row (status: queued)
  Return forecast ID to user immediately
        |
        v
  [Background worker]
        |
        +---> Download HRRR GRIB2 from AWS S3 (status: fetching_weather)
        +---> Extract U/V wind, reproject to DEM CRS, write speed/dir grids
        +---> Generate WindNinja config
        +---> docker run WindNinja_cli (status: running_solver)
        +---> On success: status -> completed
        +---> On failure: status -> failed, store error_message
```

## Files Implemented

| File | Purpose |
|------|---------|
| `backend/config.py` | App settings via pydantic-settings (DB URL, data dir, solver image) |
| `backend/models/database.py` | SQLAlchemy engine, session factory, declarative Base |
| `backend/models/orm.py` | ORM models: ForecastArea, ElevationTile, LandCoverTile, Forecast |
| `backend/models/schemas.py` | Pydantic request/response schemas |
| `backend/api/main.py` | FastAPI app with CORS and router registration |
| `backend/api/deps.py` | FastAPI dependencies (DB session, settings) |
| `backend/api/routers/forecast_areas.py` | ForecastArea CRUD endpoints (stub) |
| `backend/api/routers/forecasts.py` | Forecast submission and status endpoints (stub) |
| `docker-compose.yml` | Postgres-only (backend runs natively) |
| `.env.example` | Environment variable documentation |

## Remaining Work

- Initialize Alembic and generate first migration
- Implement terrain service (py3dep for DEM, LANDFIRE API for LCP)
- Implement weather service (Herbie for HRRR, GRIB-to-ASCII conversion)
- Implement solver service (WindNinja config generation, Docker execution)
- Implement all API endpoint handlers
- Integration test: create forecast -> poll -> retrieve output
