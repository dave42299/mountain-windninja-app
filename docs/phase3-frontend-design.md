# Phase 3: Frontend UI Design Report

**Date:** May 21, 2026
**Status:** Complete -- React + TypeScript SPA with MapLibre map, forecast submission, status polling, output viewer, saved locations, and dark mode. Connected to Phase 2 backend via Vite dev proxy.

## Objective

Build a responsive single-page application that lets users request wind forecasts by clicking on a map, monitor pipeline progress in real time, browse forecast history, and download results -- providing an intuitive visual interface to the Phase 2 backend API.

## Scope Assumptions

- **Single-user local dev.** No authentication. The app connects to the local backend via Vite proxy.
- **No wind visualization.** Phase 3 provides file listing and download for completed forecasts. Animated wind particles over 3D terrain are deferred to Phase 5 (CesiumJS + cesium-wind-layer).
- **Polling, not WebSocket.** TanStack Query's `refetchInterval` is sufficient for forecast status updates (forecasts take minutes). Real-time push is deferred to Phase 4/5.
- **Free map tiles only.** CARTO Positron basemap (no API key) for Phase 3. Terrain/satellite tiles via MapTiler can be added later.

## Key Design Decisions

### 1. Map-first UX: click to forecast

The primary interaction is visual and spatial. The home page is a full-viewport map. Users click anywhere on the map to place a pin, which immediately opens a side panel with forecast parameters pre-filled. This removes the friction of typing coordinates and makes the geographic context (terrain, nearby peaks) immediately visible.

The forecast form slides in from the left as a Sheet (shadcn), keeping the map visible behind it. The domain extent overlay (dashed blue square) updates in real time as the user adjusts the size slider, giving immediate spatial feedback about what area the solver will cover.

### 2. Adaptive polling with status-based intervals

Different pipeline stages have different expected durations. Rather than polling at a fixed interval, the `useForecast` hook adjusts its `refetchInterval` based on the current status:

| Status | Poll interval | Rationale |
|--------|--------------|-----------|
| queued | 5s | Should transition quickly |
| fetching_terrain | 10s | DEM download takes 10-60s |
| fetching_weather | 10s | HRRR GRIB download takes 10-30s per timestep |
| running_solver | 15s | Momentum solver takes 30-120s per timestep |
| completed/failed/cancelled | disabled | Terminal states, no more changes |

The list view (`useForecasts`) also auto-refreshes every 5s, but only while at least one forecast in the response is in an active state.

### 3. Typed API client mirroring backend schemas

Rather than generating types from OpenAPI, we maintain a hand-written `types.ts` that mirrors the backend Pydantic schemas exactly. This is intentional for Phase 3:

- The schema surface is small (7 interfaces, 3 union types)
- Hand-written types avoid build-time codegen dependencies
- Type names match backend naming conventions for easy cross-referencing
- Changes to backend schemas during development are immediately visible as TS errors

The API client (`client.ts`) is a thin wrapper around `fetch` with typed error handling (`ApiError` class with `status` and parsed `detail`).

### 4. Vite proxy eliminates CORS complexity

All API calls from the frontend go to `/api/...` which Vite's dev server proxies to `http://localhost:8000` (stripping the `/api` prefix). This avoids CORS issues entirely during development and mirrors how a production reverse proxy would work.

### 5. Nav bar portal pattern for map-page actions

Map overlays (zoom controls, markers) compete for screen real estate with UI buttons. Rather than stacking buttons on the map, we render map-page-specific actions ("Saved", "Recent") into the nav bar via React `createPortal`. This keeps the map clean and puts navigation-level actions where users expect them.

### 6. shadcn/ui + Tailwind CSS v4 for rapid iteration

shadcn/ui provides copy-paste React components built on Radix primitives. They're fully customizable (no black-box library), tree-shake naturally (each component is a local file), and support dark mode via CSS variables. Tailwind CSS v4 (with the `@tailwindcss/vite` plugin) eliminates the need for a separate config file and provides sub-second HMR.

### 7. Dark mode via CSS custom properties

The `index.css` defines two complete color palettes (light and dark) using CSS custom properties. A `ThemeToggle` component in the nav bar persists the user's preference to `localStorage` and toggles the `dark` class on `<html>`. All shadcn components and custom styles automatically respond.

## Architecture

```
Browser (localhost:5173)
├── Vite dev server (HMR + proxy)
│   └── /api/* → http://localhost:8000/* (strips /api prefix)
├── React 19 + TypeScript 5
│   ├── TanStack Query v5 (server state, polling, cache)
│   ├── React Router v7 (client-side routing)
│   ├── React Hook Form + Zod (form validation)
│   └── react-map-gl + MapLibre GL JS (map rendering)
└── shadcn/ui + Tailwind CSS v4 (component library)
```

### Data flow

```
User clicks map → MapView.onLocationSelect
  → MapPage sets selectedLocation state
  → Sheet opens with ForecastForm
  → User submits → useCreateForecast mutation
    → POST /api/forecasts/ → backend returns 201
    → Toast notification → navigate to /forecasts/:id
    → ForecastDetailPage polls via useForecast(id)
      → Status transitions render in StepIndicator
      → On completed: OutputViewer fetches file list
```

### Component hierarchy

```
App (ErrorBoundary → QueryClientProvider → BrowserRouter → Toaster)
└── AppLayout (nav bar + theme toggle + nav-portal)
    ├── MapPage
    │   ├── MapView (MapLibre + markers + domain overlay)
    │   ├── ForecastForm (Sheet, left panel)
    │   ├── ForecastSidebar (right panel, recent forecasts)
    │   └── SavedNavButton (portal → nav bar)
    ├── DashboardPage (table + tabs + pagination)
    └── ForecastDetailPage
        ├── StepIndicator (pipeline progress)
        ├── OutputViewer (file table + download links)
        └── ForecastDetailMap (static map inset)
```

## Routes

| Path | Page | Purpose |
|------|------|---------|
| `/` | MapPage | Click-to-forecast map with form and sidebar |
| `/dashboard` | DashboardPage | Filterable, paginated forecast history |
| `/forecasts/:id` | ForecastDetailPage | Status, progress, metadata, output, map inset |
| `*` | NotFoundPage | 404 catch-all |

## API Client Layer

### Module structure

| File | Purpose |
|------|---------|
| `src/api/types.ts` | TypeScript interfaces mirroring backend schemas |
| `src/api/client.ts` | Base fetch wrapper (`get`, `post`, `del`, `ApiError`) |
| `src/api/forecasts.ts` | Forecast CRUD + output listing + download URL builder |
| `src/api/forecast-areas.ts` | ForecastArea CRUD |

### TanStack Query hooks

| Hook | Key | Behavior |
|------|-----|----------|
| `useForecasts(params)` | `["forecasts", params]` | Paginated list, 5s auto-refresh while active |
| `useForecast(id)` | `["forecast", id]` | Single forecast, adaptive polling by status |
| `useCreateForecast()` | mutation | Invalidates `["forecasts"]` on success |
| `useForecastOutput(id, status)` | `["forecast-output", id]` | Enabled only when `status === "completed"` |
| `useForecastAreas()` | `["forecast-areas"]` | All saved locations |
| `useCreateForecastArea()` | mutation | Invalidates `["forecast-areas"]` |
| `useDeleteForecastArea()` | mutation | Invalidates `["forecast-areas"]` |

## UX Patterns

### Map interaction

- Full-viewport map with crosshair cursor (clear "click to select" affordance)
- Click places a pin marker + dashed domain extent square
- Domain square updates in real time with size slider
- Saved locations appear as bookmark icons on the map
- Pitch at 45° gives terrain depth perception even without 3D elevation

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
- **Dashboard**: Tabular view with status filter tabs (All/Active/Completed/Failed)
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
| Server state | TanStack Query | 5 | Polling, caching, mutations |
| Map | MapLibre GL JS | 4.7 | Vector map rendering |
| Map bindings | react-map-gl | 7.1 | React wrapper for MapLibre |
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
| `frontend/vite.config.ts` | Vite + React + Tailwind + `/api` proxy |
| `frontend/tsconfig.json` | Project references (app + node) |
| `frontend/tsconfig.app.json` | App TS config with `@` path alias |
| `frontend/components.json` | shadcn/ui configuration |
| `frontend/index.html` | Entry HTML |
| `frontend/src/main.tsx` | React DOM entry point |
| `frontend/src/App.tsx` | ErrorBoundary + QueryClient + Router + Toaster |
| `frontend/src/index.css` | Tailwind v4 + light/dark CSS variables |
| `frontend/src/lib/utils.ts` | `cn()` class merge helper |
| `frontend/src/api/types.ts` | TypeScript interfaces (mirrors backend) |
| `frontend/src/api/client.ts` | Fetch wrapper with `ApiError` |
| `frontend/src/api/forecasts.ts` | Forecast API functions |
| `frontend/src/api/forecast-areas.ts` | ForecastArea API functions |
| `frontend/src/hooks/use-forecasts.ts` | TanStack Query hooks with adaptive polling |
| `frontend/src/hooks/use-forecast-areas.ts` | ForecastArea query hooks |
| `frontend/src/layouts/AppLayout.tsx` | Nav bar + theme toggle + portal slot + outlet |
| `frontend/src/pages/MapPage.tsx` | Map + form sheet + sidebar + saved locations |
| `frontend/src/pages/DashboardPage.tsx` | Filterable paginated forecast table |
| `frontend/src/pages/ForecastDetailPage.tsx` | Status + progress + metadata + output + map inset |
| `frontend/src/pages/NotFoundPage.tsx` | 404 page |
| `frontend/src/components/MapView.tsx` | MapLibre map with click, pin, domain overlay, saved markers |
| `frontend/src/components/ForecastForm.tsx` | Zod-validated submission form |
| `frontend/src/components/ForecastSidebar.tsx` | Recent forecasts panel + nav portal toggle |
| `frontend/src/components/ForecastDetailMap.tsx` | Static map inset for detail page |
| `frontend/src/components/OutputViewer.tsx` | File table with type recognition + download links |
| `frontend/src/components/SavedLocations.tsx` | Save/load/delete locations + save button |
| `frontend/src/components/StatusBadge.tsx` | Colored status badge component |
| `frontend/src/components/StepIndicator.tsx` | Pipeline step progress display |
| `frontend/src/components/ThemeToggle.tsx` | Light/dark mode toggle with localStorage |
| `frontend/src/components/ErrorBoundary.tsx` | Global React error boundary |
| `frontend/src/components/ui/*.tsx` | shadcn/ui primitives (button, card, input, label, select, badge, separator, sheet, dialog, tabs, sonner, skeleton) |

## Phase 3 Completion Summary

All Phase 3 work is complete. The frontend provides:

- **Map-based location picking** with domain extent visualization
- **Forecast submission** with full Zod validation and backend connectivity
- **Real-time status monitoring** via adaptive polling and step indicators
- **Forecast dashboard** with status filtering and pagination
- **Output file viewer** with type recognition and direct download
- **Saved locations** with save/load/delete and map marker display
- **Dark mode** with persistent preference
- **Error handling** via global boundary, 404 page, and toast notifications
- **Responsive layout** with nav portal pattern for clean map UX
