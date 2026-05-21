import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { useCreateForecast } from "@/hooks/use-forecasts";
import { SaveLocationButton } from "@/components/SavedLocations";
import type { SelectedLocation } from "@/types/map";

const forecastSchema = z.object({
  size_km: z.coerce.number().min(1).max(50),
  forecast_start: z.string().min(1, "Forecast start is required"),
  duration_hours: z.coerce.number().int().min(1).max(48),
  weather_model: z.enum(["hrrr"]),
  solver_type: z.enum(["mass_conservation", "momentum"]),
  output_wind_height: z.coerce.number().min(0.1).max(100),
});

type ForecastFormValues = z.infer<typeof forecastSchema>;

function getDefaultStartTime(): string {
  const now = new Date();
  now.setMinutes(0, 0, 0);
  now.setHours(now.getHours() + 1);
  return now.toISOString().slice(0, 16);
}

interface ForecastFormProps {
  location: SelectedLocation;
  domainSizeKm: number;
  onDomainSizeChange: (size: number) => void;
  onClose: () => void;
}

export default function ForecastForm({
  location,
  domainSizeKm,
  onDomainSizeChange,
  onClose,
}: ForecastFormProps) {
  const navigate = useNavigate();
  const createForecast = useCreateForecast();

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<ForecastFormValues>({
    resolver: zodResolver(forecastSchema),
    defaultValues: {
      size_km: domainSizeKm,
      forecast_start: getDefaultStartTime(),
      duration_hours: 6,
      weather_model: "hrrr",
      solver_type: "mass_conservation",
      output_wind_height: 10,
    },
  });

  const watchedSizeKm = watch("size_km");

  const onSubmit = (values: ForecastFormValues) => {
    const startDate = new Date(values.forecast_start);
    const forecastStartIso = startDate.toISOString();

    createForecast.mutate(
      {
        latitude: location.latitude,
        longitude: location.longitude,
        size_km: values.size_km,
        forecast_start: forecastStartIso,
        duration_hours: values.duration_hours,
        weather_model: values.weather_model,
        solver_type: values.solver_type,
        output_wind_height: values.output_wind_height,
      },
      {
        onSuccess: (forecast) => {
          toast.success("Forecast submitted", {
            description: `${values.duration_hours}h ${values.weather_model.toUpperCase()} forecast queued`,
          });
          onClose();
          navigate(`/forecasts/${forecast.id}`);
        },
        onError: (error) => {
          toast.error("Failed to submit forecast", {
            description: error.message,
          });
        },
      },
    );
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
      <div className="flex items-start justify-between">
        <div>
          <Label className="text-xs text-muted-foreground">Location</Label>
          <p className="mt-1 font-mono text-sm">
            {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}
          </p>
        </div>
        <SaveLocationButton
          latitude={location.latitude}
          longitude={location.longitude}
          sizeKm={watchedSizeKm}
        />
      </div>

      <div>
        <Label htmlFor="size_km">Domain size (km)</Label>
        <div className="mt-1.5 flex items-center gap-3">
          <input
            type="range"
            min={1}
            max={50}
            step={1}
            className="h-2 flex-1 cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
            {...register("size_km", {
              onChange: (e) => onDomainSizeChange(Number(e.target.value)),
            })}
          />
          <span className="w-10 text-right text-sm font-medium">
            {watchedSizeKm}
          </span>
        </div>
        {errors.size_km && (
          <p className="mt-1 text-xs text-destructive">
            {errors.size_km.message}
          </p>
        )}
      </div>

      <Separator />

      <div>
        <Label htmlFor="forecast_start">Forecast start</Label>
        <Input
          id="forecast_start"
          type="datetime-local"
          className="mt-1.5"
          {...register("forecast_start")}
        />
        {errors.forecast_start && (
          <p className="mt-1 text-xs text-destructive">
            {errors.forecast_start.message}
          </p>
        )}
      </div>

      <div>
        <Label htmlFor="duration_hours">Duration (hours)</Label>
        <div className="mt-1.5 flex items-center gap-3">
          <input
            type="range"
            min={1}
            max={48}
            step={1}
            className="h-2 flex-1 cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
            {...register("duration_hours")}
          />
          <span className="w-10 text-right text-sm font-medium">
            {watch("duration_hours")}
          </span>
        </div>
        {errors.duration_hours && (
          <p className="mt-1 text-xs text-destructive">
            {errors.duration_hours.message}
          </p>
        )}
      </div>

      <Separator />

      <div>
        <Label>Weather model</Label>
        <Select
          defaultValue="hrrr"
          onValueChange={(val) =>
            setValue("weather_model", val as "hrrr")
          }
        >
          <SelectTrigger className="mt-1.5">
            <SelectValue />
          </SelectTrigger>
          {/* Only HRRR is supported today; NBM backend support is deferred */}
          <SelectContent>
            <SelectItem value="hrrr">HRRR (3 km)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label>Solver type</Label>
        <Select
          defaultValue="mass_conservation"
          onValueChange={(val) =>
            setValue(
              "solver_type",
              val as "mass_conservation" | "momentum",
            )
          }
        >
          <SelectTrigger className="mt-1.5">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="mass_conservation">
              Mass Conservation (fast)
            </SelectItem>
            <SelectItem value="momentum">Momentum (OpenFOAM)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label htmlFor="output_wind_height">Wind height (m)</Label>
        <Input
          id="output_wind_height"
          type="number"
          step="0.1"
          min="0.1"
          max="100"
          className="mt-1.5"
          {...register("output_wind_height")}
        />
        {errors.output_wind_height && (
          <p className="mt-1 text-xs text-destructive">
            {errors.output_wind_height.message}
          </p>
        )}
      </div>

      <Separator />

      <div className="flex gap-2">
        <Button
          type="submit"
          className="flex-1"
          disabled={createForecast.isPending}
        >
          {createForecast.isPending ? "Submitting..." : "Run Forecast"}
        </Button>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
