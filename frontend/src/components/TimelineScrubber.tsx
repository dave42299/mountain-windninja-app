import { useEffect, useRef, useCallback } from "react";
import { Play, Pause, ChevronLeft, ChevronRight } from "lucide-react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";

interface TimelineScrubberProps {
  timestepCount: number;
  currentTimestep: number;
  onTimestepChange: (timestep: number) => void;
  validTime: string | null;
  isPlaying: boolean;
  onPlayToggle: () => void;
}

const PLAYBACK_INTERVAL_MS = 2000;

export default function TimelineScrubber({
  timestepCount,
  currentTimestep,
  onTimestepChange,
  validTime,
  isPlaying,
  onPlayToggle,
}: TimelineScrubberProps) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stepForward = useCallback(() => {
    onTimestepChange((currentTimestep + 1) % timestepCount);
  }, [currentTimestep, timestepCount, onTimestepChange]);

  const stepBack = useCallback(() => {
    onTimestepChange(
      (currentTimestep - 1 + timestepCount) % timestepCount,
    );
  }, [currentTimestep, timestepCount, onTimestepChange]);

  useEffect(() => {
    if (isPlaying) {
      intervalRef.current = setInterval(stepForward, PLAYBACK_INTERVAL_MS);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPlaying, stepForward]);

  const formattedTime = validTime
    ? format(new Date(validTime), "MMM d, yyyy HH:mm 'UTC'")
    : `Timestep ${currentTimestep + 1}`;

  const hasMultipleTimesteps = timestepCount > 1;

  return (
    <div className="flex items-center gap-2 rounded-lg border bg-background/90 px-3 py-2 shadow-md backdrop-blur-sm">
      {hasMultipleTimesteps && (
        <>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={stepBack}
            aria-label="Previous timestep"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onPlayToggle}
            aria-label={isPlaying ? "Pause" : "Play"}
          >
            {isPlaying ? (
              <Pause className="h-4 w-4" />
            ) : (
              <Play className="h-4 w-4" />
            )}
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={stepForward}
            aria-label="Next timestep"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>

          <input
            type="range"
            min={0}
            max={timestepCount - 1}
            value={currentTimestep}
            onChange={(e) => onTimestepChange(Number(e.target.value))}
            className="mx-2 h-1.5 w-32 cursor-pointer appearance-none rounded-full bg-muted accent-primary sm:w-48"
          />
        </>
      )}

      <span className="min-w-[140px] text-xs text-muted-foreground">
        {formattedTime}
      </span>
    </div>
  );
}
