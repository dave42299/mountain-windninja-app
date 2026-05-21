import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ForecastStatus } from "@/api/types";

const statusConfig: Record<
  ForecastStatus,
  { label: string; className: string }
> = {
  queued: {
    label: "Queued",
    className: "bg-blue-100 text-blue-800 border-blue-200",
  },
  fetching_terrain: {
    label: "Terrain",
    className: "bg-indigo-100 text-indigo-800 border-indigo-200",
  },
  fetching_weather: {
    label: "Weather",
    className: "bg-yellow-100 text-yellow-800 border-yellow-200",
  },
  running_solver: {
    label: "Solving",
    className: "bg-orange-100 text-orange-800 border-orange-200",
  },
  completed: {
    label: "Completed",
    className: "bg-green-100 text-green-800 border-green-200",
  },
  failed: {
    label: "Failed",
    className: "bg-red-100 text-red-800 border-red-200",
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-gray-100 text-gray-800 border-gray-200",
  },
};

interface StatusBadgeProps {
  status: ForecastStatus;
  className?: string;
}

export default function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = statusConfig[status];
  return (
    <Badge
      variant="outline"
      className={cn(config.className, className)}
    >
      {config.label}
    </Badge>
  );
}
