import { useState } from "react";
import { useNavigate } from "react-router";
import { format } from "date-fns";
import { Plus, Wind } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import StatusBadge from "@/components/StatusBadge";
import { useForecasts } from "@/hooks/use-forecasts";
import type { ForecastStatus } from "@/api/types";

type StatusFilter = "all" | "completed" | "failed";

function statusFilterToParam(
  filter: StatusFilter,
): ForecastStatus | undefined {
  switch (filter) {
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    default:
      return undefined;
  }
}

const PAGE_SIZE = 20;

export default function DashboardPage() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);

  const statusParam = statusFilterToParam(statusFilter);
  const { data, isLoading } = useForecasts({
    status: statusParam,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const items = data?.items ?? [];
  const totalCount = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const handleFilterChange = (value: string) => {
    setStatusFilter(value as StatusFilter);
    setPage(0);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">Forecasts</h1>
          <p className="text-sm text-muted-foreground">
            {totalCount} total forecast{totalCount !== 1 ? "s" : ""}
          </p>
        </div>
        <Button onClick={() => navigate("/")} className="gap-1.5">
          <Plus className="h-4 w-4" />
          New Forecast
        </Button>
      </div>

      <div className="border-b px-6 py-3">
        <Tabs value={statusFilter} onValueChange={handleFilterChange}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="completed">Completed</TabsTrigger>
            <TabsTrigger value="failed">Failed</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="p-8 text-center text-sm text-muted-foreground">
            Loading forecasts...
          </div>
        )}

        {!isLoading && items.length === 0 && (
          <div className="flex flex-col items-center gap-3 p-12 text-center">
            <Wind className="h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">
              No forecasts match this filter
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/")}
            >
              Create your first forecast
            </Button>
          </div>
        )}

        {items.length > 0 && (
          <table className="w-full">
            <thead className="sticky top-0 bg-background">
              <tr className="border-b text-left text-xs font-medium text-muted-foreground">
                <th className="px-6 py-3">Status</th>
                <th className="px-6 py-3">Location</th>
                <th className="px-6 py-3">Start</th>
                <th className="px-6 py-3">Duration</th>
                <th className="px-6 py-3">Solver</th>
                <th className="px-6 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((forecast) => (
                <tr
                  key={forecast.id}
                  onClick={() => navigate(`/forecasts/${forecast.id}`)}
                  className="cursor-pointer border-b transition-colors hover:bg-accent/50"
                >
                  <td className="px-6 py-3">
                    <StatusBadge status={forecast.status} />
                  </td>
                  <td className="px-6 py-3 font-mono text-xs">
                    {forecast.center_latitude.toFixed(4)},{" "}
                    {forecast.center_longitude.toFixed(4)}
                  </td>
                  <td className="px-6 py-3 text-sm">
                    {format(
                      new Date(forecast.forecast_start),
                      "MMM d, HH:mm",
                    )}
                  </td>
                  <td className="px-6 py-3 text-sm">
                    {forecast.duration_hours}h
                  </td>
                  <td className="px-6 py-3 text-sm">
                    {forecast.solver_type === "momentum"
                      ? "Momentum"
                      : "Mass Cons."}
                  </td>
                  <td className="px-6 py-3 text-xs text-muted-foreground">
                    {format(
                      new Date(forecast.created_at),
                      "MMM d, HH:mm",
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t px-6 py-3">
          <p className="text-xs text-muted-foreground">
            Page {page + 1} of {totalPages}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
