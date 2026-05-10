# Project Goals and Background

## Purpose

Create a web application that allows users to easily generate detailed, high-resolution wind forecasts for a specific point on Earth. The app targets complex mountain terrain where standard weather forecasts lack the resolution to capture terrain-driven wind effects (channeling, acceleration over ridges, turbulence in valleys, etc.).

## How It Works

The application chains together several data sources and models:

1. **Weather forecast input** -- Publicly available forecast data from NOAA's HRRR (High Resolution Rapid Refresh) model serves as the large-scale wind forcing. HRRR runs hourly at ~3 km resolution and is freely available via AWS S3 (`noaa-hrrr-bdp-pds`). The NBM (National Blend of Models) is supported as a secondary option.

2. **WindNinja solver** -- WindNinja is a diagnostic wind model developed by the USDA Forest Service Fire Lab for wildland fire modeling. Given a coarse weather forecast, terrain elevation, and land cover data, it computes high-resolution (down to ~100 m) 3D wind fields that account for terrain effects. It supports both a conservation-of-mass solver (fast) and an OpenFOAM-based momentum solver (more accurate for complex terrain). WindNinja runs as a CLI tool inside a Docker container.

3. **Terrain elevation data (DEM)** -- Digital Elevation Models provide the 3D surface the wind flows over. Sources include USGS 3DEP (US, up to 1 m resolution), SRTM (global, 30 m), and GMTED (global, coarser). WindNinja accepts GeoTIFF or ASC format.

4. **Land cover data (LCP)** -- LANDFIRE Landscape files provide vegetation type, canopy height, and fuel model data for the US. This lets WindNinja account for surface roughness (e.g., dense forest vs. alpine rock vs. open meadow) when computing wind fields.

## Reference Implementation

The project builds on and extends the CLI-based workflow at [Austfi/mountain_windninja](https://github.com/Austfi/mountain_windninja), which provides:
- A Docker image packaging WindNinja + OpenFOAM + GDAL
- Shell scripts for terrain fetching (DEM + LCP)
- HRRR forecast download and preprocessing
- WindNinja execution and output archiving (KMZ + ASCII grids)
- Domain management (register lat/lon areas with terrain)

This project replaces the CLI front-end with a web application and adds cloud orchestration and 3D visualization.

## Key Goals

### 1. User Interface for Forecast Input
A web-based map UI where users can:
- Click on a map or enter lat/lon coordinates to select a forecast location
- Specify a domain size (e.g., 10-12 km square)
- Choose forecast start time and duration
- Select the weather model (HRRR, NBM)
- View job status and history

### 2. Automated Terrain and Land Cover Retrieval
Given a lat/lon and domain size, the backend automatically:
- Downloads the DEM from USGS 3DEP (US) or SRTM (global)
- Downloads LANDFIRE LCP data (US) for vegetation/land cover
- Caches terrain data so repeat runs for the same area are fast

### 3. Recurring Weather Forecast Ingestion
- Download HRRR forecast GRIB2 files from AWS S3 on a schedule (every 1-6 hours)
- Support on-demand downloads for specific forecast cycles
- Use the Herbie Python library for efficient HRRR access

### 4. Cloud-Based Solver Execution
- Run the WindNinja Docker container on cloud compute (GCP Cloud Run Jobs, AWS Batch, or similar)
- Support both mass-conservation and momentum (OpenFOAM) solver modes
- Scale to handle multiple concurrent forecast requests
- Track job status and notify users on completion

### 5. Cloud Storage for Output Archives
- Store completed WindNinja output (KMZ, ASCII grids, metadata) in cloud storage (GCS or S3)
- Organize by domain, forecast cycle, and run timestamp
- Provide download links and API access to archived results

### 6. 3D Wind Visualization
- Display wind forecast results as animated particles over 3D terrain in the browser
- Use CesiumJS for the 3D globe and terrain rendering
- Use cesium-wind-layer for GPU-accelerated wind particle animation
- Timeline scrubber for multi-hour forecasts
- Color-code wind speed, show direction vectors

## Data Sources Reference

| Data | Source | Coverage | Format | Access |
|------|--------|----------|--------|--------|
| Weather forecast | NOAA HRRR | CONUS | GRIB2 | AWS S3 (free, no auth) |
| Weather forecast | NOAA NBM | CONUS | GRIB2 | AWS S3 / NOMADS |
| Terrain DEM | USGS 3DEP | United States | GeoTIFF (COG) | National Map API |
| Terrain DEM | SRTM | Global (60N-56S) | GeoTIFF | OpenTopography API (key required) |
| Terrain DEM | GMTED | Global | GeoTIFF | USGS |
| Land cover | LANDFIRE LCP | United States | LCP | LFPS API |

## Technology Stack

- **Frontend:** React + TypeScript, CesiumJS (via resium), cesium-wind-layer
- **Backend:** Python, FastAPI, SQLAlchemy, GDAL, Herbie, rasterio
- **Solver:** WindNinja CLI in Docker (with OpenFOAM)
- **Cloud:** GCP or AWS (compute, storage, task queue, scheduler)
- **Infrastructure:** Terraform
- **Database:** PostgreSQL
