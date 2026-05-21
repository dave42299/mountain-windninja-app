import { Check, Circle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ForecastStatus } from "@/api/types";

interface Step {
  key: ForecastStatus;
  label: string;
}

const PIPELINE_STEPS: Step[] = [
  { key: "queued", label: "Queued" },
  { key: "fetching_terrain", label: "Fetching Terrain" },
  { key: "fetching_weather", label: "Fetching Weather" },
  { key: "running_solver", label: "Running Solver" },
  { key: "completed", label: "Completed" },
];

const STATUS_ORDER: Record<string, number> = {
  queued: 0,
  fetching_terrain: 1,
  fetching_weather: 2,
  running_solver: 3,
  completed: 4,
  failed: -1,
  cancelled: -1,
};

interface StepIndicatorProps {
  currentStatus: ForecastStatus;
}

export default function StepIndicator({ currentStatus }: StepIndicatorProps) {
  const currentIndex = STATUS_ORDER[currentStatus] ?? -1;

  return (
    <div className="flex items-center gap-1">
      {PIPELINE_STEPS.map((step, index) => {
        const isComplete = currentIndex > index;
        const isCurrent = currentIndex === index;

        return (
          <div key={step.key} className="flex items-center gap-1">
            {index > 0 && (
              <div
                className={cn(
                  "h-0.5 w-6",
                  isComplete ? "bg-primary" : "bg-border",
                )}
              />
            )}
            <div className="flex flex-col items-center gap-1">
              <div
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full border-2",
                  isComplete && "border-primary bg-primary text-primary-foreground",
                  isCurrent && "border-primary",
                  !isComplete && !isCurrent && "border-border",
                )}
              >
                {isComplete && <Check className="h-3.5 w-3.5" />}
                {isCurrent && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                )}
                {!isComplete && !isCurrent && (
                  <Circle className="h-2.5 w-2.5 text-muted-foreground" />
                )}
              </div>
              <span
                className={cn(
                  "text-[10px] leading-tight",
                  isCurrent
                    ? "font-medium text-foreground"
                    : "text-muted-foreground",
                )}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
