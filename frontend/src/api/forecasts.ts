import { buildDownloadUrl, get, post } from "./client";
import type {
  ForecastCreate,
  ForecastOutputResponse,
  ForecastResponse,
  ForecastStatus,
  PaginatedForecastResponse,
  WindFieldResponse,
} from "./types";

export interface ListForecastsParams {
  status?: ForecastStatus;
  forecastAreaId?: string;
  limit?: number;
  offset?: number;
}

export function createForecast(
  body: ForecastCreate,
): Promise<ForecastResponse> {
  return post<ForecastResponse>("/forecasts/", body);
}

export function listForecasts(
  params: ListForecastsParams = {},
  signal?: AbortSignal,
): Promise<PaginatedForecastResponse> {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set("status", params.status);
  if (params.forecastAreaId)
    searchParams.set("forecast_area_id", params.forecastAreaId);
  if (params.limit != null) searchParams.set("limit", String(params.limit));
  if (params.offset != null) searchParams.set("offset", String(params.offset));

  const query = searchParams.toString();
  const path = query ? `/forecasts/?${query}` : "/forecasts/";
  return get<PaginatedForecastResponse>(path, signal);
}

export function getForecast(
  id: string,
  signal?: AbortSignal,
): Promise<ForecastResponse> {
  return get<ForecastResponse>(`/forecasts/${id}`, signal);
}

export function getForecastOutput(
  id: string,
  signal?: AbortSignal,
): Promise<ForecastOutputResponse> {
  return get<ForecastOutputResponse>(`/forecasts/${id}/output`, signal);
}

export function getForecastOutputDownloadUrl(
  forecastId: string,
  filename: string,
): string {
  return buildDownloadUrl(`/forecasts/${forecastId}/output/${filename}`);
}

export function getWindField(
  forecastId: string,
  timestep: number,
  signal?: AbortSignal,
): Promise<WindFieldResponse> {
  return get<WindFieldResponse>(
    `/forecasts/${forecastId}/wind-field/${timestep}`,
    signal,
  );
}
