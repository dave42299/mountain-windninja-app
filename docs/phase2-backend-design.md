# Phase 2: Backend API Design Report

**Date:** May 14, 2026
**Status:** In progress -- terrain pipeline implemented and reviewed; weather, solver, and full forecast HTTP handlers still pending

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

Terrain tiles are cached by a **WGS84** axis-aligned bounding box stored on each tile row (north, east, south, west in decimal degrees). That stored box is taken **from the downloaded file** (via GDAL / rasterio after write) so the index reflects **actual on-disk extent**.

**Lookup vs download.** The user's true request is a square from **center + ``size_km``** (the **user bbox**). Before fetching, we **pad** that square (default **25%** on each half-span) to form a **download bbox** that is sent to USGS / LANDFIRE. Padding exists so **substantially similar** later requests (slightly different center or size) still fall inside data we already pulled.

**Cache queries use the user bbox, not the padded bbox.** A hit is any tile whose **stored** (file-derived) bbox **fully contains** the **user** box for the current forecast. If we queried with the padded box, we would require the cache to match a **larger** region than the user actually asked for, which would **defeat** the purpose of padding (fewer hits, wrong semantics). Padding only enlarges the **fetch**; the **question** to the cache is always "do we already have real pixels covering **this user's** box?"

**Tile selection.** Among hits, **elevation** picks the **smallest** containing tile (tightest fit). **Land cover** picks the **most recently downloaded** among tiles that contain the user box, so newer LANDFIRE data is preferred when several tiles qualify.

This padding strategy is sufficient for Phase 2 and can be revisited if needed.

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
  id, bbox_north/south/east/west [indexed], crs_epsg, file_path, source,
  downloaded_at, file_size_bytes (bigint)

LandCoverTile (cached LCP files)
  id, bbox_north/south/east/west [indexed], crs_epsg, file_path, source,
  downloaded_at, file_size_bytes (bigint)

Forecast (a single wind forecast job)
  id, forecast_area_id (nullable FK -> SET NULL) [indexed],
  center_latitude, center_longitude, size_km,
  elevation_tile_id (FK -> RESTRICT), land_cover_tile_id (nullable FK -> RESTRICT),
  status (enum) [indexed], weather_model (enum), solver_type (enum), output_wind_height,
  forecast_start, duration_hours,
  error_message, created_at [indexed], started_at, completed_at, updated_at (auto)
```

Enums (defined in `backend/models/orm.py`, used by ORM defaults and Pydantic schemas):
- **ForecastStatus:** queued, fetching_weather, running_solver, completed, failed
- **WeatherModel:** hrrr, nbm
- **SolverType:** mass_conservation, momentum

Relationships:
- ForecastArea has many Forecasts (optional grouping; SET NULL on area deletion)
- ElevationTile is referenced by many Forecasts (RESTRICT deletion)
- LandCoverTile is referenced by many Forecasts (nullable for non-US; RESTRICT deletion)

Indexes:
- Tile bbox columns are individually indexed for bitmap AND scans on spatial containment queries
- `forecasts.status` for polling active/queued jobs
- `forecasts.forecast_area_id` for listing forecasts per saved area
- `forecasts.created_at` for listing recent forecasts

Tile cache selection strategy (implemented as classmethods on tile models). Both use **containment of the user's true WGS84 bbox** (not the padded download bbox):

- **ElevationTile:** smallest tile that fully contains the user bbox (tightest spatial fit).
- **LandCoverTile:** most recently downloaded tile that fully contains the user bbox (newest land cover when several tiles qualify).

Stale job detection:
- `updated_at` is auto-set on every row update via SQLAlchemy `onupdate`. A forecast stuck in `running_solver` with a stale `updated_at` indicates a dead background worker.

Naming convention:
- `latitude` / `longitude` for user-input single-point coordinates (API create schemas)
- `center_latitude` / `center_longitude` for area/domain center points (ORM, response schemas, ForecastArea)
- `bbox_north/south/east/west` for bounding boxes (tile tables)

File path convention:
- Tile `file_path` values are stored relative to `settings.data_dir` (e.g. `elevation/abc123.tif`). The service layer resolves them to absolute paths at read time.

Database initialization:
- `database.py` has zero side effects at import time. It defines `Base` and provides `build_engine()` / `build_session_factory()` factory functions. The engine is created lazily by `deps.py` (via `@lru_cache`) on first HTTP request. This allows tests to override the URL and Alembic to manage its own engine independently.

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
  Compute user bbox (square from center + size_km)
        |
        v
  Compute padded bbox (e.g. 25% buffer) for download only
        |
        +---> Query elevation_tiles: stored bbox contains **user** bbox?
        |       |-- Yes: reuse cached tile
        |       |-- No:  download using **padded** bbox, insert row (stored bbox from file)
        |
        +---> Query land_cover_tiles: stored bbox contains **user** bbox?
        |       |-- Yes: reuse cached tile
        |       |-- No:  download using **padded** bbox, insert row (stored bbox from file)
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

## Terrain service

### Design principles

These principles were established during terrain service development and should guide the rest of the backend:

- **Make invalid states unrepresentable.** Value objects validate at construction. ``Wgs84BoundingBox`` enforces ``north > south`` and ``east > west`` via ``__post_init__``; code that receives one can trust it without re-checking. Domain size is capped (50 km) to prevent runaway downloads before the request reaches any external API.

- **Single public surface, layered internals.** ``terrain.py`` is the only module other code imports. Source-specific download logic (USGS 3DEP, LANDFIRE LCP) and pure geometry live in sub-modules the public API calls but external code never touches.

- **Independent layer durability.** DEM and LCP are independent caches with independent transaction commits. If LCP fails after DEM succeeds, the DEM row and file survive so the next attempt retries only the failed layer.

- **Metadata reflects reality, not intent.** Stored bbox columns are populated from the file actually written to disk, not from the padded request that triggered the download. Cache queries answer "do we have pixels here?" not "did we ask for pixels here?"

- **No orphans on failure.** Every download path cleans up partial files if metadata extraction or ORM insertion fails. A committed tile row always has a valid file behind it.

- **Typed errors for each failure mode.** ``TerrainDemError``, ``TerrainLcpError``, and ``TerrainOutsideUsError`` let the API layer map failures to appropriate HTTP responses without inspecting messages.

### Key invariants

- A ``Wgs84BoundingBox`` always satisfies ``north > south`` and ``east > west``.
- Cache lookup uses the **user bbox**; padding only enlarges the **download**.
- A tile row is never committed without the corresponding file existing on disk.
- A ``Forecast`` row is never inserted until both tile IDs exist.
- The terrain service owns its own transaction commits; callers must not wrap terrain resolution and Forecast insertion in a single transaction.

### Implementation summary

The terrain layer turns a forecast location (center lat/lon + ``size_km``) into two on-disk assets plus database rows: a DEM (GeoTIFF) and land cover (LANDFIRE LCP with ``.prj`` sidecar).

**Orchestration.** ``ensure_tiles_for_forecast`` builds the user bbox, pads it (default 25%), validates the padded extent falls inside CONUS, and resolves each layer. The frozen ``ForecastTerrainTiles`` result carries both tiles plus user and padded bboxes for downstream callers (solver config, logging).

**Why DEM and LCP use different runtimes.** Elevation uses py3dep on the host (USGS 3DEP at 10 m, reprojected to UTM). Land cover uses WindNinja's ``fetch_dem`` inside the solver Docker image (LANDFIRE source), reusing the same image as solver runs so the host doesn't need to duplicate the LCP/GDAL toolchain.

**Cache eviction.** Tiles currently accumulate without bound. A disk-budget or age-based eviction strategy is deferred to Phase 4; ``file_size_bytes`` on tile rows supports future budget-based cleanup without filesystem scanning.

**Tests.** Fast unit tests cover geometry, orchestration, and partial-failure durability; DEM/LCP I/O is mocked. Optional integration tests (``RUN_TERRAIN_INTEGRATION=1``) hit live USGS for manual validation.

### Status

The terrain service is **complete and reviewed**. All design principles, invariants, cache semantics, error handling, and file cleanup paths are implemented and tested (44 unit tests passing). No known bugs or gaps remain for the Phase 2 scope.

## Import Conventions

Within a package, use relative imports (`from .database import Base`). Between packages, use absolute imports from the project root (`from models.database import build_engine`). Enforced via `.cursor/rules/import-conventions.mdc`.

## App Startup

The FastAPI lifespan handler creates the data directory structure on first startup:
`data/{elevation, land_cover, output, weather}/`. The `data/` directory is git-ignored and convention-based -- the path is controlled by `settings.data_dir`.

## Files Implemented

| File | Purpose |
|------|---------|
| `backend/config.py` | App settings via pydantic-settings (DB URL, data dir, solver image, LCP timeout, CORS origins) |
| `backend/models/database.py` | Declarative Base, engine/session factory builders (zero import side effects) |
| `backend/models/enums.py` | ForecastStatus, WeatherModel, SolverType enums (no heavy imports) |
| `backend/models/orm.py` | ORM models, tile cache selection classmethods |
| `backend/models/schemas.py` | Pydantic request/response schemas with UUID validation |
| `backend/api/main.py` | FastAPI app with lifespan, configurable CORS, router registration |
| `backend/api/deps.py` | FastAPI dependencies: lazy DB engine (@lru_cache), session, settings |
| `backend/api/routers/forecast_areas.py` | ForecastArea CRUD endpoints |
| `backend/api/routers/forecasts.py` | Forecast routes (stub; module doc describes calling terrain before insert) |
| `backend/services/terrain_geometry.py` | Pure WGS84 bbox, square construction, fractional padding, CONUS validation |
| `backend/services/terrain_dem.py` | USGS 3DEP DEM download via py3dep, UTM reprojection |
| `backend/services/terrain_lcp.py` | LANDFIRE LCP via Docker ``fetch_dem``, ``.prj`` sidecar generation |
| `backend/services/terrain.py` | Public terrain API: cache lookup, metadata extraction, orchestration |
| `backend/tests/test_terrain_*.py` | Terrain unit tests and optional integration (env-gated) |
| `backend/requirements.txt` | Pinned dependencies for Docker layer caching (derived from pyproject.toml) |
| `backend/Dockerfile` | Python 3.12 image with GDAL, deps-first layer caching |
| `docker-compose.yml` | Postgres-only (backend runs natively) |
| `.env.example` | Environment variable documentation |
| `.cursor/rules/import-conventions.mdc` | Import convention rule (relative within, absolute across) |
| `.cursor/rules/variable-naming.mdc` | Readable variable naming rule |

## Remaining Work

- Wire ``POST /forecasts`` to call ``ensure_tiles_for_forecast`` before inserting ``Forecast`` (see ``backend/api/routers/forecasts.py`` module doc)
- Implement weather service (Herbie for HRRR, GRIB-to-ASCII conversion)
- Implement solver service (WindNinja config generation, Docker execution)
- Implement remaining API endpoint handlers and background job lifecycle
- End-to-end integration test: create forecast -> poll -> retrieve output
