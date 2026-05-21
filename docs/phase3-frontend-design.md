# Phase 3: Frontend UI Design Report

**Date:** May 21, 2026
**Status:** Complete -- React + TypeScript SPA with CesiumJS 3D map, forecast submission, status polling, output viewer, saved locations, dark mode, and 3D wind vector field visualization (arrow overlay + particle animation). Connected to Phase 2 backend via Vite dev proxy.

## Objective

Build a responsive single-page application that lets users request wind forecasts by clicking on a 3D map, monitor pipeline progress in real time, browse forecast history, and download results -- providing an intuitive visual interface to the Phase 2 backend API.

## Scope Assumptions

- **Single-user local dev.** No authentication. The app connects to the local backend via Vite proxy.
- **Wind visualization complete (Phase 3b).** Completed forecasts display a 3D arrow vector field over terrain (primary mode) with adaptive density, plus an animated GPU-accelerated particle mode (secondary). Timeline scrubber, speed legend, visualization mode toggle, and show/hide toggle are included.
- **Polling, not WebSocket.** TanStack Query's `refetchInterval` is sufficient for forecast status updates (forecasts take minutes). Real-time push is deferred.
- **Cesium Ion free tier.** Provides Cesium World Terrain and Bing imagery. Token stored in `frontend/.env` (gitignored), placeholder in `.env.example`.

## Key Design Decisions

### 1. Map-first UX: click to forecast

The primary interaction is visual and spatial. The home page is a full-viewport CesiumJS 3D globe. Users click anywhere on the globe to place a pin, which immediately opens a side panel with forecast parameters pre-filled. This removes the friction of typing coordinates and makes the geographic context (terrain, nearby peaks) immediately visible.

The forecast form slides in from the left as a Sheet (shadcn), keeping the map visible behind it. The domain extent overlay (blue rectangle) updates in real time as the user adjusts the size slider, giving immediate spatial feedback about what area the solver will cover.

### 2. CesiumJS for 3D terrain from day one

The original plan called for MapLibre GL (2D) in Phase 3 with CesiumJS deferred to Phase 5. During implementation, Phase 3 and Phase 5's map work were collapsed into a single phase. CesiumJS (via resium) now serves as the sole map library, providing:

- 3D terrain rendering with Cesium World Terrain
- Globe navigation (zoom, tilt, rotate) built in
- Terrain-clamped markers via `HeightReference.CLAMP_TO_GROUND`
- Foundation for cesium-wind-layer particle visualization (next step)

Shared Cesium utilities (terrain provider, domain rectangle math, color constants) are extracted into `lib/cesium-utils.ts` to avoid duplication between `CesiumMapView` and `CesiumDetailMap`.

### 3. Adaptive polling with status-based intervals

Different pipeline stages have different expected durations. Rather than polling at a fixed interval, the `useForecast` hook adjusts its `refetchInterval` based on the current status:

| Status | Poll interval | Rationale |
|--------|--------------|-----------|
| queued | 5s | Should transition quickly |
| fetching_terrain | 10s | DEM download takes 10-60s |
| fetching_weather | 10s | HRRR GRIB download takes 10-30s per timestep |
| running_solver | 15s | Momentum solver takes 30-120s per timestep |
| completed/failed/cancelled | disabled | Terminal states, no more changes |

The list view (`useForecasts`) also auto-refreshes every 5s, but only while at least one forecast in the response is in an active state.

### 4. Typed API client with abort support

The API client (`client.ts`) is a thin wrapper around `fetch` with typed error handling (`ApiError` class with `status` and parsed `detail`). All fetch functions accept an `AbortSignal` parameter, and TanStack Query hooks thread `context.signal` through to enable automatic request cancellation on unmount or query invalidation.

Hand-written `types.ts` mirrors the backend Pydantic schemas exactly. Shared constants like `ACTIVE_STATUSES` and `isTerminalStatus()` are defined once and imported everywhere.

### 5. Vite proxy eliminates CORS complexity

All API calls from the frontend go to `/api/...` which Vite's dev server proxies to `http://localhost:8000` (stripping the `/api` prefix). This avoids CORS issues entirely during development and mirrors how a production reverse proxy would work.

### 6. Nav bar portal pattern for map-page actions

Map overlays (zoom controls, markers) compete for screen real estate with UI buttons. Rather than stacking buttons on the map, we render map-page-specific actions ("Saved", "Recent") into the nav bar via React `createPortal`. The Saved Locations dropdown uses a Radix `Popover` for proper focus management and click-outside dismissal.

### 7. shadcn/ui + Tailwind CSS v4 for rapid iteration

shadcn/ui provides copy-paste React components built on Radix primitives. They're fully customizable (no black-box library), tree-shake naturally (each component is a local file), and support dark mode via CSS variables. Tailwind CSS v4 (with the `@tailwindcss/vite` plugin) eliminates the need for a separate config file and provides sub-second HMR.

### 8. Dark mode via CSS custom properties

The `index.css` defines two complete color palettes (light and dark) using CSS custom properties. A `ThemeToggle` component in the nav bar persists the user's preference to `localStorage` and toggles the `dark` class on `<html>`. An inline script in `index.html` applies the saved theme synchronously before React mounts, preventing a flash of wrong theme.

### 9. Lazy-loaded pages

All page components are wrapped in `React.lazy()` with a `Suspense` fallback. This defers the ~4MB CesiumJS bundle until the user navigates to a page that uses the 3D map, keeping the initial load lean for the Dashboard page.

## Architecture

```
Browser (localhost:5173)
├── Vite dev server (HMR + proxy)
│   └── /api/* → http://localhost:8000/* (strips /api prefix)
├── React 19 + TypeScript 5
│   ├── TanStack Query v5 (server state, polling, cache, abort)
│   ├── React Router v7 (client-side routing)
│   ├── React Hook Form + Zod (form validation)
│   └── CesiumJS via resium (3D map rendering)
└── shadcn/ui + Tailwind CSS v4 (component library)
```

### Data flow

```
User clicks globe → CesiumMapView.onLocationSelect (globe.pick → Cartographic)
  → MapPage sets selectedLocation state
  → Sheet opens with ForecastForm
  → User submits → useCreateForecast mutation
    → POST /api/forecasts/ → backend returns 201
    → Toast notification → navigate to /forecasts/:id
    → ForecastDetailPage polls via useForecast(id)
      → Status transitions render in StepIndicator
      → On completed:
        → Full-width CesiumDetailMap renders with onViewerReady callback
        → useWindField(forecastId, currentTimestep, status) fetches wind data
        → WindArrowOverlay builds PolylineCollection arrows (default mode)
          OR WindOverlay creates/updates WindLayer particles (alt mode)
        → Visualization mode toggle switches between Arrows and Particles
        → TimelineScrubber controls currentTimestep (play/step/slider)
        → WindLegend displays speed range in mph
        → OutputViewer fetches file list
```

### Component hierarchy

```
App (ErrorBoundary → QueryClientProvider → BrowserRouter → Suspense → Toaster)
└── AppLayout (nav bar + theme toggle + nav-portal)
    ├── MapPage (lazy)
    │   ├── CesiumMapView (3D globe + markers + domain overlay)
    │   ├── ForecastForm (Sheet, left panel)
    │   ├── ForecastSidebar (right panel, recent forecasts)
    │   └── SavedNavButton (portal → nav bar, Popover dropdown)
    ├── DashboardPage (lazy, table + tabs + pagination)
    └── ForecastDetailPage (lazy)
        ├── StepIndicator (pipeline progress)
        ├── CesiumDetailMap (full-width for completed, map inset otherwise)
        │   ├── WindArrowOverlay (Cesium PolylineCollection arrows, default mode)
        │   └── WindOverlay (cesium-wind-layer GPU particles, alt mode)
        ├── TimelineScrubber (play/pause/step + slider, bottom-left overlay)
        ├── WindLegend (color scale, bottom-right overlay)
        ├── Viz mode toggle (Arrows / Particles, bottom-right overlay)
        └── OutputViewer (file table + download links)
```

## Routes

| Path | Page | Purpose |
|------|------|---------|
| `/` | MapPage | Click-to-forecast 3D map with form and sidebar |
| `/dashboard` | DashboardPage | Filterable, paginated forecast history |
| `/forecasts/:id` | ForecastDetailPage | Status, progress, metadata, output, map inset |
| `*` | NotFoundPage | 404 catch-all |

## API Client Layer

### Module structure

| File | Purpose |
|------|---------|
| `src/api/types.ts` | TypeScript interfaces mirroring backend schemas + shared constants |
| `src/api/client.ts` | Base fetch wrapper (`get`, `post`, `del`, `ApiError`) with abort support |
| `src/api/forecasts.ts` | Forecast CRUD + output listing + download URL builder |
| `src/api/forecast-areas.ts` | ForecastArea CRUD |
| `src/api/query-keys.ts` | Centralized query key factory |

### TanStack Query hooks

| Hook | Key | Behavior |
|------|-----|----------|
| `useForecasts(params)` | `["forecasts", params]` | Paginated list, 5s auto-refresh while active |
| `useForecast(id)` | `["forecast", id]` | Single forecast, adaptive polling by status |
| `useCreateForecast()` | mutation | Invalidates `["forecasts"]` on success |
| `useForecastOutput(id, status)` | `["forecast-output", id]` | Enabled only when `status === "completed"` |
| `useWindField(id, timestep, status)` | `["forecast-wind-field", id, timestep]` | Enabled only when `status === "completed"`, `staleTime: Infinity` (immutable data) |
| `useForecastAreas()` | `["forecast-areas"]` | All saved locations |
| `useCreateForecastArea()` | mutation | Invalidates `["forecast-areas"]` |
| `useDeleteForecastArea()` | mutation | Invalidates `["forecast-areas"]` |

## UX Patterns

### Map interaction

- Full-viewport CesiumJS 3D globe with crosshair cursor
- Click places a terrain-clamped pin marker + domain extent rectangle
- Domain rectangle updates in real time with size slider
- Saved locations appear as terrain-clamped point markers on the globe
- Full 3D navigation: zoom, tilt, rotate via Cesium's built-in controls

### Forecast submission

- Sheet slides in from the left (map stays visible behind)
- Location is read-only (from map click); domain size is adjustable
- Forecast start defaults to next rounded hour
- Duration, weather model, solver type, wind height are all configurable
- "Save location" button available inline for quick area reuse
- On submit: toast → navigate to detail page

### Status feedback

- **Sidebar**: Recent forecasts with colored status badges, auto-refreshing
- **Detail page**: Step indicator with spinning loader on current stage
- **Dashboard**: Tabular view with status filter tabs (All/Completed/Failed)
- **Failed state**: Red alert card with full error message from backend

### Output access

- File table with recognized types (Wind Grid, Projection, Config, Metadata, Raster, Google Earth)
- Human-readable sizes (B/KB/MB/GB)
- Direct download via anchor links to `/api/forecasts/{id}/output/{filename}`
- Disabled/hidden when forecast is not yet completed

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Build | Vite | 6 | Dev server, HMR, proxy, bundling |
| Framework | React | 19 | UI rendering |
| Language | TypeScript | 5.7 | Type safety |
| Routing | React Router | 7 | Client-side navigation |
| Server state | TanStack Query | 5 | Polling, caching, mutations, abort |
| 3D Map | CesiumJS | 1.141 | 3D globe and terrain rendering |
| Map bindings | resium | 1.21 | React wrapper for CesiumJS |
| Wind arrows | Cesium PolylineCollection | (core) | 3D arrow vector field overlay (primary mode) |
| Wind particles | cesium-wind-layer | 0.10 | GPU-accelerated wind particle animation (secondary mode) |
| Vite plugin | vite-plugin-cesium-engine | 1.6 | WASM workers, assets, CSS injection |
| UI components | shadcn/ui | latest | Radix-based accessible components |
| Styling | Tailwind CSS | 4 | Utility-first CSS |
| Forms | React Hook Form | 7 | Performant form state |
| Validation | Zod | 3 | Schema validation |
| Dates | date-fns | 4 | Date formatting |
| Icons | Lucide React | latest | Consistent icon set |
| Toasts | Sonner | 1.7 | Toast notifications |

## Files Implemented

| File | Purpose |
|------|---------|
| `frontend/package.json` | Dependencies and scripts |
| `frontend/vite.config.ts` | Vite + React + Tailwind + Cesium + `/api` proxy |
| `frontend/tsconfig.json` | Project references (app + node) |
| `frontend/tsconfig.app.json` | App TS config with `@` path alias |
| `frontend/components.json` | shadcn/ui configuration |
| `frontend/index.html` | Entry HTML with dark-mode inline script |
| `frontend/.env.example` | Cesium Ion token placeholder |
| `frontend/src/main.tsx` | React DOM entry point + Cesium Ion init |
| `frontend/src/App.tsx` | ErrorBoundary + QueryClient + Router + Suspense + Toaster |
| `frontend/src/index.css` | Tailwind v4 + light/dark CSS variables |
| `frontend/src/lib/utils.ts` | `cn()` class merge helper |
| `frontend/src/lib/cesium.ts` | Cesium Ion token initialization |
| `frontend/src/lib/cesium-utils.ts` | Shared terrain provider, domain rectangle math, color constants |
| `frontend/src/api/types.ts` | TypeScript interfaces + `ACTIVE_STATUSES` + `isTerminalStatus` |
| `frontend/src/api/client.ts` | Fetch wrapper with `ApiError` and abort support |
| `frontend/src/api/forecasts.ts` | Forecast API functions |
| `frontend/src/api/forecast-areas.ts` | ForecastArea API functions |
| `frontend/src/api/query-keys.ts` | Centralized query key factory |
| `frontend/src/hooks/use-forecasts.ts` | TanStack Query hooks with adaptive polling and abort |
| `frontend/src/hooks/use-forecast-areas.ts` | ForecastArea query hooks with abort |
| `frontend/src/types/map.ts` | `SelectedLocation` and `SavedLocationMarker` types |
| `frontend/src/layouts/AppLayout.tsx` | Nav bar + theme toggle + portal slot + outlet |
| `frontend/src/pages/MapPage.tsx` | 3D map + form sheet + sidebar + saved locations (Popover) |
| `frontend/src/pages/DashboardPage.tsx` | Filterable paginated forecast table |
| `frontend/src/pages/ForecastDetailPage.tsx` | Status + progress + metadata + output + 3D map inset |
| `frontend/src/pages/NotFoundPage.tsx` | 404 page |
| `frontend/src/components/CesiumMapView.tsx` | CesiumJS 3D globe with click, pin, domain overlay, saved markers |
| `frontend/src/components/CesiumDetailMap.tsx` | CesiumJS map for detail page (full-width with viewer callback for wind overlay) |
| `frontend/src/components/WindArrowOverlay.tsx` | 3D arrow vector field via Cesium PolylineCollection with adaptive density (default mode) |
| `frontend/src/components/WindOverlay.tsx` | Imperative cesium-wind-layer lifecycle (create/update/destroy WindLayer, secondary mode) |
| `frontend/src/components/TimelineScrubber.tsx` | Play/pause, step forward/back, range slider, UTC time display; graceful single-timestep handling |
| `frontend/src/components/WindLegend.tsx` | Color gradient bar with speed labels (mph) |
| `frontend/src/lib/wind-arrows.ts` | Grid subsampling, speed-to-color mapping, arrow geometry (shaft + arrowhead) |
| `frontend/src/components/ForecastForm.tsx` | Zod-validated submission form |
| `frontend/src/components/ForecastSidebar.tsx` | Recent forecasts panel + nav portal toggle |
| `frontend/src/components/OutputViewer.tsx` | File table with type recognition + download links |
| `frontend/src/components/SavedLocations.tsx` | Save/load/delete locations + save button |
| `frontend/src/components/StatusBadge.tsx` | Colored status badge component |
| `frontend/src/components/StepIndicator.tsx` | Pipeline step progress display |
| `frontend/src/components/ThemeToggle.tsx` | Light/dark mode toggle with localStorage |
| `frontend/src/components/ErrorBoundary.tsx` | Global React error boundary |
| `frontend/src/components/ui/*.tsx` | shadcn/ui primitives (button, card, input, label, select, badge, separator, sheet, dialog, tabs, popover, sonner, skeleton) |

## Phase 3 Completion Summary

All Phase 3 and Phase 3b work is complete. The frontend provides:

- **3D map-based location picking** with CesiumJS terrain rendering and domain extent visualization
- **Forecast submission** with full Zod validation and backend connectivity
- **Real-time status monitoring** via adaptive polling and step indicators
- **Forecast dashboard** with status filtering and pagination
- **Output file viewer** with type recognition and direct download
- **Saved locations** with save/load/delete, Popover dropdown, and terrain-clamped map markers
- **Dark mode** with persistent preference (flash-free)
- **Error handling** via global boundary, 404 page, and toast notifications
- **Lazy loading** for Cesium-heavy pages to keep initial bundle lean
- **Request cancellation** via AbortController threading through TanStack Query
- **3D arrow vector field** (default mode) via Cesium PolylineCollection with speed-based coloring, direction-aware arrows, and adaptive density based on camera zoom level
- **Animated wind particle visualization** (secondary mode) via cesium-wind-layer with GPU-accelerated rendering, tuned for visibility (slower, thicker, longer-lived particles)
- **Visualization mode toggle** for switching between Arrows and Particles rendering modes
- **Timeline scrubber** for navigating multi-hour forecast timesteps with play/pause animation; always visible when wind data exists (graceful single-timestep handling)
- **Wind speed legend** with color gradient and mph labels
- **Show/hide wind toggle** for toggling wind layer visibility
