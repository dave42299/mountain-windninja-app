const MPS_TO_MPH = 2.23694;

const GRADIENT_COLORS = [
  "#3b82f6",
  "#22d3ee",
  "#22c55e",
  "#eab308",
  "#f97316",
  "#ef4444",
];

interface WindLegendProps {
  speedMinMps: number;
  speedMaxMps: number;
}

export default function WindLegend({ speedMinMps, speedMaxMps }: WindLegendProps) {
  const minMph = Math.round(speedMinMps * MPS_TO_MPH);
  const maxMph = Math.round(speedMaxMps * MPS_TO_MPH);
  const midMph = Math.round(((speedMinMps + speedMaxMps) / 2) * MPS_TO_MPH);

  const gradient = `linear-gradient(to right, ${GRADIENT_COLORS.join(", ")})`;

  return (
    <div className="rounded-lg border bg-background/90 px-3 py-2 shadow-md backdrop-blur-sm">
      <div className="mb-1 text-[10px] font-medium text-muted-foreground">
        Wind Speed (mph)
      </div>
      <div
        className="h-2.5 w-36 rounded-sm"
        style={{ background: gradient }}
      />
      <div className="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>{minMph}</span>
        <span>{midMph}</span>
        <span>{maxMph}</span>
      </div>
    </div>
  );
}
