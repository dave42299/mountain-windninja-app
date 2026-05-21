import { buildDownloadUrl, get, post } from "./client";
import type {
  ForecastCreate,
  ForecastOutputResponse,
  ForecastResponse,
  ForecastStatus,
  PaginatedForecastResponse,
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
): Promise<PaginatedForecastResponse> {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set("status", params.status);
  if (params.forecastAreaId)
    searchParams.set("forecast_area_id", params.forecastAreaId);
  if (params.limit != null) searchParams.set("limit", String(params.limit));
  if (params.offset != null) searchParams.set("offset", String(params.offset));

  const query = searchParams.toString();
  const path = query ? `/forecasts/?${query}` : "/forecasts/";
  return get<PaginatedForecastResponse>(path);
}

export function getForecast(id: string): Promise<ForecastResponse> {
  return get<ForecastResponse>(`/forecasts/${id}`);
}

export function getForecastOutput(id: string): Promise<ForecastOutputResponse> {
  return get<ForecastOutputResponse>(`/forecasts/${id}/output`);
}

export function getForecastOutputDownloadUrl(
  forecastId: string,
  filename: string,
): string {
  return buildDownloadUrl(`/forecasts/${forecastId}/output/${filename}`);
}
