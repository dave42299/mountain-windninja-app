import { useState } from "react";
import MapView, { type SelectedLocation } from "@/components/MapView";

export default function MapPage() {
  const [selectedLocation, setSelectedLocation] =
    useState<SelectedLocation | null>(null);
  const [domainSizeKm] = useState(12);

  return (
    <div className="relative h-full">
      <MapView
        selectedLocation={selectedLocation}
        onLocationSelect={setSelectedLocation}
        domainSizeKm={domainSizeKm}
      />

      {selectedLocation && (
        <div className="absolute bottom-4 left-4 rounded-lg border bg-background/95 px-4 py-3 shadow-lg backdrop-blur-sm">
          <p className="text-xs font-medium text-muted-foreground">
            Selected location
          </p>
          <p className="mt-0.5 text-sm font-mono">
            {selectedLocation.latitude.toFixed(5)},{" "}
            {selectedLocation.longitude.toFixed(5)}
          </p>
        </div>
      )}
    </div>
  );
}
