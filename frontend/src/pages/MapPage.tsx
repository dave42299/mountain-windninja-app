import { useState } from "react";
import { createPortal } from "react-dom";
import CesiumMapView from "@/components/CesiumMapView";
import type { SelectedLocation } from "@/types/map";
import ForecastForm from "@/components/ForecastForm";
import ForecastSidebar from "@/components/ForecastSidebar";
import SavedLocations from "@/components/SavedLocations";
import { useForecastAreas } from "@/hooks/use-forecast-areas";
import { Bookmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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
    setIsFormOpen(true);
  };

  const handleClose = () => {
    setIsFormOpen(false);
  };

  return (
    <div className="relative h-full">
      <CesiumMapView
        selectedLocation={selectedLocation}
        onLocationSelect={handleLocationSelect}
        domainSizeKm={domainSizeKm}
        savedLocations={savedMarkers}
      />

      <SavedNavButton onSelectLocation={handleSavedLocationSelect} />

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

function SavedNavButton({
  onSelectLocation,
}: {
  isOpen: boolean;
  onToggle: () => void;
  onSelectLocation: (location: SelectedLocation, sizeKm: number) => void;
}) {
  const portalTarget = document.getElementById("nav-portal");

  if (!portalTarget) return null;

  return createPortal(
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5">
          <Bookmark className="h-4 w-4" />
          Saved
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-0">
        <div className="px-3 py-2">
          <span className="text-xs font-semibold">Saved Locations</span>
        </div>
        <SavedLocations onSelectLocation={onSelectLocation} />
      </PopoverContent>
    </Popover>,
    portalTarget,
  );
}
