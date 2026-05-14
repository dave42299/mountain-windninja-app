"""Forecast HTTP routes.

When ``POST /forecasts`` is implemented, resolve terrain before inserting ``Forecast``:

- Call :func:`services.terrain.ensure_tiles_for_forecast` with the request center and
  ``size_km``. That helper **commits after each layer** (DEM, then LCP) so the caches
  stay independent: e.g. LCP failure still leaves a successful DEM insert for the next
  request.
- Insert ``Forecast`` referencing ``elevation_tile_id`` / ``land_cover_tile_id`` from
  the returned :class:`services.terrain.ForecastTerrainTiles`. If that step fails,
  retries reuse both tiles without re-downloading (do not roll back across an already
  committed terrain layer).

**Transaction boundary contract:** ``ensure_tiles_for_forecast`` owns its own commits
internally (one per layer). The endpoint must **not** wrap terrain resolution and
Forecast insertion in a single transaction. Instead, call terrain resolution first
(which commits tile rows), then insert and commit the Forecast row separately. This
ensures that already-committed tiles survive if the Forecast insert fails.

A dev-only ``GET /debug/terrain`` is optional for manual QA; not required for Phase 2.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/forecasts", tags=["forecasts"])
