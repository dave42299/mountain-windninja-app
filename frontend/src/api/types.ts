export type ForecastStatus =
  | "queued"
  | "fetching_terrain"
  | "fetching_weather"
  | "running_solver"
  | "completed"
  | "failed"
  | "cancelled";

export type WeatherModel = "hrrr" | "nbm";

export type SolverType = "mass_conservation" | "momentum";

// --- ForecastArea ---

export interface ForecastAreaCreate {
  center_latitude: number;
  center_longitude: number;
  size_km?: number;
  label?: string;
}

export interface ForecastAreaResponse {
  id: string;
  label: string | null;
  center_latitude: number;
  center_longitude: number;
  size_km: number;
  created_at: string;
}

// --- Forecast ---

export interface ForecastCreate {
  forecast_area_id?: string;
  latitude?: number;
  longitude?: number;
  size_km?: number;
  forecast_start: string;
  duration_hours: number;
  weather_model?: WeatherModel;
  solver_type?: SolverType;
  output_wind_height?: number;
}

export interface ForecastResponse {
  id: string;
  forecast_area_id: string | null;
  center_latitude: number;
  center_longitude: number;
  size_km: number;
  elevation_tile_id: string | null;
  land_cover_tile_id: string | null;
  status: ForecastStatus;
  weather_model: WeatherModel;
  solver_type: SolverType;
  output_wind_height: number;
  forecast_start: string;
  duration_hours: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

// --- Paginated listing ---

export interface PaginatedForecastResponse {
  items: ForecastResponse[];
  total: number;
  limit: number;
  offset: number;
}

// --- Forecast Output ---

export interface OutputFileInfo {
  filename: string;
  size_bytes: number;
}

export interface ForecastOutputResponse {
  forecast_id: string;
  files: OutputFileInfo[];
}

// --- Error responses ---

export interface ValidationErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface ConflictDetail {
  message: string;
  forecast_id: string;
  status: string;
  retry_after_seconds: number | null;
}
