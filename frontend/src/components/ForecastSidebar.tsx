import { useNavigate } from "react-router";
import { formatDistanceToNow } from "date-fns";
import { ChevronRight, Clock, Wind } from "lucide-react";
import { useForecasts } from "@/hooks/use-forecasts";
import StatusBadge from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface ForecastSidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}

export default function ForecastSidebar({
  isOpen,
  onToggle,
}: ForecastSidebarProps) {
  const navigate = useNavigate();
  const { data, isLoading } = useForecasts({ limit: 10 });

  if (!isOpen) {
    return (
      <Button
        variant="outline"
        size="sm"
        className="absolute right-4 top-4 z-10 gap-1.5 bg-background/95 shadow-lg backdrop-blur-sm"
        onClick={onToggle}
      >
        <Clock className="h-4 w-4" />
        Recent
      </Button>
    );
  }

  return (
    <div className="absolute right-0 top-0 z-10 flex h-full w-80 flex-col border-l bg-background/95 shadow-lg backdrop-blur-sm">
      <div className="flex items-center justify-between px-4 py-3">
        <h3 className="text-sm font-semibold">Recent Forecasts</h3>
        <Button variant="ghost" size="sm" onClick={onToggle}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      <Separator />

      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="p-4 text-center text-sm text-muted-foreground">
            Loading...
          </div>
        )}

        {data && data.items.length === 0 && (
          <div className="flex flex-col items-center gap-2 p-8 text-center">
            <Wind className="h-8 w-8 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">
              No forecasts yet. Click the map to start one.
            </p>
          </div>
        )}

        {data?.items.map((forecast) => (
          <button
            key={forecast.id}
            onClick={() => navigate(`/forecasts/${forecast.id}`)}
            className="w-full border-b px-4 py-3 text-left transition-colors hover:bg-accent"
          >
            <div className="flex items-center justify-between">
              <StatusBadge status={forecast.status} />
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(forecast.created_at), {
                  addSuffix: true,
                })}
              </span>
            </div>
            <p className="mt-1.5 font-mono text-xs">
              {forecast.center_latitude.toFixed(4)},{" "}
              {forecast.center_longitude.toFixed(4)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {forecast.duration_hours}h &middot;{" "}
              {forecast.weather_model.toUpperCase()} &middot;{" "}
              {forecast.solver_type === "momentum" ? "Momentum" : "Mass Cons."}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
