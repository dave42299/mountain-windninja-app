import { useParams } from "react-router";
import { Wind } from "lucide-react";
import { useForecast } from "@/hooks/use-forecasts";

export default function ForecastDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: forecast, isLoading, error } = useForecast(id);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading forecast...</p>
      </div>
    );
  }

  if (error || !forecast) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-destructive">
          {error?.message ?? "Forecast not found"}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <div className="flex items-center gap-3">
        <Wind className="h-6 w-6" />
        <h1 className="text-2xl font-bold">Forecast Detail</h1>
      </div>
      <div className="mt-6 space-y-2 text-sm">
        <p>
          <span className="font-medium">Status:</span> {forecast.status}
        </p>
        <p>
          <span className="font-medium">Location:</span>{" "}
          {forecast.center_latitude.toFixed(4)},{" "}
          {forecast.center_longitude.toFixed(4)}
        </p>
        <p>
          <span className="font-medium">Model:</span> {forecast.weather_model}
        </p>
        <p>
          <span className="font-medium">Solver:</span> {forecast.solver_type}
        </p>
        <p>
          <span className="font-medium">Duration:</span>{" "}
          {forecast.duration_hours}h
        </p>
        {forecast.error_message && (
          <p className="text-destructive">
            <span className="font-medium">Error:</span>{" "}
            {forecast.error_message}
          </p>
        )}
      </div>
    </div>
  );
}
