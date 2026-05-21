import { del, get, post } from "./client";
import type { ForecastAreaCreate, ForecastAreaResponse } from "./types";

export function createForecastArea(
  body: ForecastAreaCreate,
): Promise<ForecastAreaResponse> {
  return post<ForecastAreaResponse>("/forecast-areas/", body);
}

export function listForecastAreas(): Promise<ForecastAreaResponse[]> {
  return get<ForecastAreaResponse[]>("/forecast-areas/");
}

export function getForecastArea(id: string): Promise<ForecastAreaResponse> {
  return get<ForecastAreaResponse>(`/forecast-areas/${id}`);
}

export function deleteForecastArea(id: string): Promise<void> {
  return del(`/forecast-areas/${id}`);
}
