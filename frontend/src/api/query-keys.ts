import type { ListForecastsParams } from "./forecasts";

export const queryKeys = {
  forecastAreas: {
    all: ["forecast-areas"] as const,
  },
  forecasts: {
    all: ["forecasts"] as const,
    list: (params: ListForecastsParams) => ["forecasts", params] as const,
    detail: (id: string | undefined) => ["forecast", id] as const,
    output: (id: string | undefined) => ["forecast-output", id] as const,
  },
} as const;
