import { LayoutDashboard } from "lucide-react";

export default function DashboardPage() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <LayoutDashboard className="mx-auto h-12 w-12 text-muted-foreground/50" />
        <h2 className="mt-4 text-lg font-medium">Forecast Dashboard</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          View and manage all your wind forecasts
        </p>
      </div>
    </div>
  );
}
