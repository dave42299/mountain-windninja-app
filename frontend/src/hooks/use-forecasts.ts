import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { ForecastCreate, ForecastStatus } from "@/api/types";
import { isTerminalStatus } from "@/api/types";
import {
  createForecast,
  getForecast,
  getForecastOutput,
  listForecasts,
  type ListForecastsParams,
} from "@/api/forecasts";
import { queryKeys } from "@/api/query-keys";

function pollingIntervalForStatus(
  status: ForecastStatus | undefined,
): number | false {
  switch (status) {
    case "queued":
      return 5_000;
    case "fetching_terrain":
      return 10_000;
    case "fetching_weather":
      return 10_000;
    case "running_solver":
      return 15_000;
    default:
      return false;
  }
}

export function useForecasts(params: ListForecastsParams = {}) {
  return useQuery({
    queryKey: queryKeys.forecasts.list(params),
    queryFn: ({ signal }) => listForecasts(params, signal),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 5_000;
      const hasActiveForecasts = data.items.some(
        (forecast) => !isTerminalStatus(forecast.status),
      );
      return hasActiveForecasts ? 5_000 : false;
    },
  });
}

export function useForecast(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.forecasts.detail(id),
    queryFn: ({ signal }) => getForecast(id!, signal),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return pollingIntervalForStatus(status);
    },
  });
}

export function useCreateForecast() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ForecastCreate) => createForecast(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.forecasts.all });
    },
  });
}

export function useForecastOutput(
  forecastId: string | undefined,
  status: ForecastStatus | undefined,
) {
  return useQuery({
    queryKey: queryKeys.forecasts.output(forecastId),
    queryFn: ({ signal }) => getForecastOutput(forecastId!, signal),
    enabled: !!forecastId && status === "completed",
  });
}
