import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createForecastArea,
  deleteForecastArea,
  listForecastAreas,
} from "@/api/forecast-areas";
import type { ForecastAreaCreate } from "@/api/types";

export function useForecastAreas() {
  return useQuery({
    queryKey: ["forecast-areas"],
    queryFn: listForecastAreas,
  });
}

export function useCreateForecastArea() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ForecastAreaCreate) => createForecastArea(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["forecast-areas"] });
    },
  });
}

export function useDeleteForecastArea() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteForecastArea(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["forecast-areas"] });
    },
  });
}
