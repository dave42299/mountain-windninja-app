# Phase 1: Local Validation Report

**Date:** May 10, 2026
**Reference repo:** [Austfi/mountain_windninja](https://github.com/Austfi/mountain_windninja) (cloned to `~/github/mountain_windninja`)

## Objective

Run the existing mountain_windninja CLI workflow end-to-end on a local Mac (Apple Silicon) to validate that all pipeline components work and to understand the data flow before building the web app.

## Environment

- **Machine:** MacBook Pro, Apple Silicon (ARM64)
- **Docker:** Docker Desktop 29.4.2, Apple Virtualization Framework with Rosetta x86_64 emulation
- **WindNinja image:** `ghcr.io/austfi/mountain-windninja:3.12.2` (linux/amd64, runs under Rosetta)
- **Test domain:** Berthoud Pass, CO (39.80, -105.78), 12 km square

## Steps Completed

### 1. Docker Image Setup

The pre-built Docker image is x86_64 only (OpenFOAM 9 has no ARM64 packages). Building natively on Apple Silicon fails at the `apt-get install openfoam9` step. The workaround is to pull the amd64 image and run under Rosetta emulation:

```bash
docker pull --platform linux/amd64 ghcr.io/austfi/mountain-windninja:3.12.2
docker tag ghcr.io/austfi/mountain-windninja:3.12.2 mountain-windninja:local
```

Platform mismatch warnings (`does not match the detected host platform`) appear on every container run. These are harmless and can be ignored.

### 2. Terrain Fetch (DEM + LCP) -- PASSED

```bash
./deploy/gcp/mwn.sh fetch-terrain --center 39.80 -105.78 --size-km 12 \
  --domain berthoud_pass --label "Berthoud Pass"
```

Downloads two files:
- `static_data/berthoud_pass.tif` -- USGS 3DEP DEM (1213x1187 pixels, 10m resolution, EPSG:32613 / UTM zone 13N)
- `static_data/berthoud_pass.lcp` -- LANDFIRE landscape file (vegetation, canopy, fuel model bands)

Both are fetched from public USGS/LANDFIRE APIs. No API keys required for US terrain.

### 3. Smoke Test (Domain-Average Wind) -- PASSED

```bash
./deploy/gcp/mwn.sh smoke --keep-temp
```

Runs WindNinja with a fixed 10 mph west wind (270 deg). Uses the OpenFOAM momentum solver with 4 threads. Completed in ~40 seconds under emulation.

**Output files** (in `runtime/temp/berthoud_pass_domavg_*/`):
| File | Contents |
|------|----------|
| `*_vel.asc` | Wind speed grid (151x151 cells, 80m resolution, mph) |
| `*_ang.asc` | Wind direction grid (azimuth degrees) |
| `*_cld.asc` | Cloud cover grid |
| `*.kmz` | Google Earth visualization |
| `*.cfg` | WindNinja config file used for the run |

Wind speeds range from near-zero in sheltered valleys to 15+ mph on exposed ridges, demonstrating that the solver correctly accounts for terrain effects.

### 4. HRRR Forecast Run via NOMADS -- FAILED

```bash
./deploy/gcp/mwn.sh run --hours 6 --keep-temp
```

WindNinja's built-in NOMADS downloader (`wx_model_type = NOMADS-HRRR-CONUS-3-KM`) failed. Root cause analysis:

1. WindNinja constructs URLs to the NOMADS GRIB filter CGI script: `https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl?...`
2. The filter returns HTTP 200 with correct GRIB headers but **zero-byte body** (`content-length: 0`)
3. WindNinja treats the empty response as a successful download, writes an empty zip, then crashes when trying to parse it
4. This affects all HRRR cycles (tested 12Z, 15Z, 16Z) -- the filter CGI is broken server-side
5. The raw GRIB2 files on NOMADS are fine (157 MB via direct URL), confirming it's the filter service, not the data
6. NOAA's production status page shows all HRRR model runs completing ON-TIME -- this is an infrastructure issue with the NOMADS filter web service, not a model production issue
7. The Akamai CDN (`akamai-request-bc` header in responses) may be involved in the empty-body issue

### 5. HRRR Forecast Run via AWS S3 + Gridded Initialization -- PASSED

Bypassed the broken NOMADS filter by downloading HRRR data directly from the AWS S3 mirror and using WindNinja's `griddedInitialization` mode.

**Step A -- Download HRRR GRIB2 from AWS S3:**
```bash
curl -o runtime/grib/hrrr.t12z.wrfsfcf02.grib2 \
  "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20260510/conus/hrrr.t12z.wrfsfcf02.grib2"
```
AWS S3 bucket `noaa-hrrr-bdp-pds` is free, requires no authentication, and mirrors all HRRR data.

**Step B -- Convert GRIB2 to speed/direction grids:**
```bash
./deploy/gcp/mwn.sh forcing-from-grib runtime/grib/hrrr.t12z.wrfsfcf02.grib2 \
  --domain berthoud_pass --time 202605101400 \
  --u-var UGRD --v-var VGRD --level 10m \
  --out runtime/temp/forcing_test
```
Extracts U/V wind components at 10m above ground, reprojects from HRRR's native Lambert conformal grid to UTM zone 13N to match the terrain, and writes `speed.asc` and `direction.asc`.

**Step C -- Run WindNinja with gridded input:**
```bash
./deploy/gcp/mwn.sh run-grid \
  --speed-grid runtime/temp/forcing_test/speed.asc \
  --direction-grid runtime/temp/forcing_test/direction.asc \
  --time 202605101400 --domain berthoud_pass --keep-temp
```
Completed in ~32 seconds. Full OpenFOAM momentum solver with real HRRR wind data.

**Note:** `run-grid` requires the DEM `.tif` file, not the `.lcp` file. The `get_gridded_domain_config()` function in the reference repo automatically falls back to `.tif` when `.lcp` is registered.

## Key Architectural Decisions for the App

### 1. Download HRRR from AWS S3, not NOMADS

WindNinja's built-in NOMADS downloader is fragile:
- Depends on the NOMADS filter CGI, which has availability issues
- Returns 200 status with empty body on failure (silent corruption)
- No fallback to alternative data sources
- Cannot be configured to use AWS S3

**Our app should download HRRR data from AWS S3** (`s3://noaa-hrrr-bdp-pds`) using the Herbie Python library. Benefits:
- AWS infrastructure is more reliable than NOMADS CGI
- Free, no authentication required
- Herbie handles multiple mirror sources with automatic fallback
- We can cache downloads and share across multiple domain runs

### 2. Use gridded initialization, not wxModelInitialization

Instead of letting WindNinja download its own weather data, we should:
1. Download HRRR GRIB2 files ourselves (backend weather service)
2. Extract U/V wind, reproject to match terrain (using GDAL, as `forcing_from_grib.py` does)
3. Feed pre-processed speed/direction grids to WindNinja via `griddedInitialization`

This decouples weather download from solver execution, enabling:
- Independent retry logic for each stage
- Pre-validation of weather data before launching the solver
- Caching of weather data across multiple domains
- Better error handling and user feedback

### 3. Docker image is x86_64 only

The WindNinja Docker image must run as linux/amd64 (OpenFOAM dependency). This is fine for:
- Cloud deployment (cloud VMs are x86_64)
- Local development (Rosetta emulation works, ~32 sec/timestep)

No need to invest in a native ARM64 build.

### 4. Solver performance baseline

On Apple Silicon under Rosetta emulation with 4 threads:
- Smoke test (domain-average, 80m mesh): ~40 seconds
- Real HRRR (gridded init, 100m mesh): ~32 seconds
- Domain size: ~12 km square

Cloud VMs (native x86_64, more cores) should be significantly faster.

## Data Flow Summary

```
HRRR GRIB2 (AWS S3)     Terrain DEM (USGS 3DEP)     Land Cover LCP (LANDFIRE)
        |                        |                            |
        v                        v                            v
  forcing-from-grib         fetch-terrain                fetch-terrain
  (extract U/V wind,       (downloads .tif)            (downloads .lcp)
   reproject to UTM)              |                            |
        |                        |                            |
        v                        v                            v
  speed.asc + dir.asc      berthoud_pass.tif          berthoud_pass.lcp
        |                        |                            |
        +------------------------+----------------------------+
                                 |
                                 v
                     WindNinja_cli (griddedInitialization)
                     OpenFOAM momentum solver
                                 |
                                 v
                    *_vel.asc  *_ang.asc  *_cld.asc
                    (wind speed, direction, cloud cover)
```
