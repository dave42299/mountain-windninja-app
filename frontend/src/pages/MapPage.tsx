import { useState } from "react";
import MapView, { type SelectedLocation } from "@/components/MapView";
import ForecastForm from "@/components/ForecastForm";
import ForecastSidebar from "@/components/ForecastSidebar";
import SavedLocations from "@/components/SavedLocations";
import { useForecastAreas } from "@/hooks/use-forecast-areas";
import { Bookmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";

export default function MapPage() {
  const [selectedLocation, setSelectedLocation] =
    useState<SelectedLocation | null>(null);
  const [domainSizeKm, setDomainSizeKm] = useState(12);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isLocationsOpen, setIsLocationsOpen] = useState(false);

  const { data: areas } = useForecastAreas();

  const savedMarkers = (areas ?? []).map((area) => ({
    id: area.id,
    latitude: area.center_latitude,
    longitude: area.center_longitude,
    label: area.label,
  }));

  const handleLocationSelect = (location: SelectedLocation) => {
    setSelectedLocation(location);
    setIsFormOpen(true);
  };

  const handleSavedLocationSelect = (
    location: SelectedLocation,
    sizeKm: number,
  ) => {
    setSelectedLocation(location);
    setDomainSizeKm(sizeKm);
    setIsLocationsOpen(false);
    setIsFormOpen(true);
  };

  const handleClose = () => {
    setIsFormOpen(false);
  };

  return (
    <div className="relative h-full">
      <MapView
        selectedLocation={selectedLocation}
        onLocationSelect={handleLocationSelect}
        domainSizeKm={domainSizeKm}
        savedLocations={savedMarkers}
      />

      <div className="absolute left-4 top-4 z-10">
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5 bg-background/95 shadow-lg backdrop-blur-sm"
          onClick={() => setIsLocationsOpen(!isLocationsOpen)}
        >
          <Bookmark className="h-4 w-4" />
          Saved
        </Button>

        {isLocationsOpen && (
          <div className="mt-2 w-64 rounded-lg border bg-background/95 shadow-lg backdrop-blur-sm">
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-xs font-semibold">Saved Locations</span>
            </div>
            <SavedLocations onSelectLocation={handleSavedLocationSelect} />
          </div>
        )}
      </div>

      <ForecastSidebar
        isOpen={isSidebarOpen}
        onToggle={() => setIsSidebarOpen((prev) => !prev)}
      />

      <Sheet open={isFormOpen} onOpenChange={setIsFormOpen}>
        <SheetContent side="left" className="w-[380px] overflow-y-auto sm:max-w-[380px]">
          <SheetHeader>
            <SheetTitle>New Forecast</SheetTitle>
            <SheetDescription>
              Configure and submit a wind forecast for this location
            </SheetDescription>
          </SheetHeader>
          {selectedLocation && (
            <div className="mt-6">
              <ForecastForm
                location={selectedLocation}
                domainSizeKm={domainSizeKm}
                onDomainSizeChange={setDomainSizeKm}
                onClose={handleClose}
              />
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
