import { del, get, post } from "./client";
import type { ForecastAreaCreate, ForecastAreaResponse } from "./types";

export function createForecastArea(
  body: ForecastAreaCreate,
): Promise<ForecastAreaResponse> {
  return post<ForecastAreaResponse>("/forecast-areas/", body);
}

export function listForecastAreas(
  signal?: AbortSignal,
): Promise<ForecastAreaResponse[]> {
  return get<ForecastAreaResponse[]>("/forecast-areas/", signal);
}

export function getForecastArea(
  id: string,
  signal?: AbortSignal,
): Promise<ForecastAreaResponse> {
  return get<ForecastAreaResponse>(`/forecast-areas/${id}`, signal);
}

export function deleteForecastArea(id: string): Promise<void> {
  return del(`/forecast-areas/${id}`);
}
