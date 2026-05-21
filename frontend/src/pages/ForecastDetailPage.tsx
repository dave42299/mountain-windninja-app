import { useParams, useNavigate, Navigate } from "react-router";
import { format } from "date-fns";
import { ArrowLeft, AlertCircle, SearchX } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/api/client";
import StatusBadge from "@/components/StatusBadge";
import StepIndicator from "@/components/StepIndicator";
import CesiumDetailMap from "@/components/CesiumDetailMap";
import OutputViewer from "@/components/OutputViewer";
import { useForecast } from "@/hooks/use-forecasts";
import { ACTIVE_STATUSES } from "@/api/types";

export default function ForecastDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: forecast, isLoading, error } = useForecast(id);

  if (!id) {
    return <Navigate to="/dashboard" replace />;
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading forecast...</p>
      </div>
    );
  }

  const isNotFound = error instanceof ApiError && error.status === 404;

  if (isNotFound) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <SearchX className="h-10 w-10 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">
          This forecast doesn't exist or has been removed.
        </p>
        <Button variant="outline" size="sm" onClick={() => navigate("/dashboard")}>
          Go to dashboard
        </Button>
      </div>
    );
  }

  if (error || !forecast) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm text-destructive">
          {error?.message ?? "Failed to load forecast"}
        </p>
        <Button variant="outline" size="sm" onClick={() => navigate(-1)}>
          Go back
        </Button>
      </div>
    );
  }

  const isActive = ACTIVE_STATUSES.has(forecast.status);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl p-6">
        <Button
          variant="ghost"
          size="sm"
          className="mb-4 gap-1.5"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>

        <div className="flex items-center gap-3">
          <StatusBadge status={forecast.status} className="text-sm px-3 py-1" />
          <h1 className="text-2xl font-bold">Forecast</h1>
        </div>

        <p className="mt-1 font-mono text-sm text-muted-foreground">
          {forecast.center_latitude.toFixed(5)},{" "}
          {forecast.center_longitude.toFixed(5)}
        </p>

        {isActive && (
          <Card className="mt-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Progress</CardTitle>
              <CardDescription>Pipeline is running...</CardDescription>
            </CardHeader>
            <CardContent>
              <StepIndicator currentStatus={forecast.status} />
            </CardContent>
          </Card>
        )}

        {forecast.status === "failed" && forecast.error_message && (
          <div className="mt-6 flex items-start gap-3 rounded-lg border border-destructive/50 bg-destructive/5 p-4">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <div>
              <p className="text-sm font-medium text-destructive">
                Forecast failed
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {forecast.error_message}
              </p>
            </div>
          </div>
        )}

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Configuration</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Weather model" value={forecast.weather_model.toUpperCase()} />
              <Row
                label="Solver"
                value={
                  forecast.solver_type === "momentum"
                    ? "Momentum (OpenFOAM)"
                    : "Mass Conservation"
                }
              />
              <Row label="Wind height" value={`${forecast.output_wind_height} m`} />
              <Row label="Domain size" value={`${forecast.size_km} km`} />
              <Row label="Duration" value={`${forecast.duration_hours} hours`} />
              <Row
                label="Forecast start"
                value={format(new Date(forecast.forecast_start), "MMM d, yyyy HH:mm")}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Timestamps</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row
                label="Created"
                value={format(new Date(forecast.created_at), "MMM d, yyyy HH:mm:ss")}
              />
              {forecast.started_at && (
                <Row
                  label="Started"
                  value={format(new Date(forecast.started_at), "MMM d, yyyy HH:mm:ss")}
                />
              )}
              {forecast.completed_at && (
                <Row
                  label="Completed"
                  value={format(new Date(forecast.completed_at), "MMM d, yyyy HH:mm:ss")}
                />
              )}
              <Row
                label="Last updated"
                value={format(new Date(forecast.updated_at), "MMM d, yyyy HH:mm:ss")}
              />
            </CardContent>
          </Card>
        </div>

        <div className="mt-6">
          <OutputViewer forecastId={forecast.id} status={forecast.status} />
        </div>

        <Card className="mt-6">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Location</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64 overflow-hidden rounded-md border">
              <CesiumDetailMap
                latitude={forecast.center_latitude}
                longitude={forecast.center_longitude}
                sizeKm={forecast.size_km}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
