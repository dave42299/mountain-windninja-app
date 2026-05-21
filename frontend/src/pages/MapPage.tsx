import { useRef, useState } from "react";
import { createPortal } from "react-dom";
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

      <SavedNavButton
        isOpen={isLocationsOpen}
        onToggle={() => setIsLocationsOpen(!isLocationsOpen)}
        onSelectLocation={handleSavedLocationSelect}
      />

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
  isOpen,
  onToggle,
  onSelectLocation,
}: {
  isOpen: boolean;
  onToggle: () => void;
  onSelectLocation: (location: SelectedLocation, sizeKm: number) => void;
}) {
  const portalTarget = document.getElementById("nav-portal");
  const buttonRef = useRef<HTMLButtonElement>(null);

  if (!portalTarget) return null;

  return (
    <>
      {createPortal(
        <div className="relative">
          <Button
            ref={buttonRef}
            variant="ghost"
            size="sm"
            className="gap-1.5"
            onClick={onToggle}
          >
            <Bookmark className="h-4 w-4" />
            Saved
          </Button>
          {isOpen && (
            <div className="absolute right-0 top-full mt-2 w-64 rounded-lg border bg-background shadow-lg">
              <div className="px-3 py-2">
                <span className="text-xs font-semibold">Saved Locations</span>
              </div>
              <SavedLocations onSelectLocation={onSelectLocation} />
            </div>
          )}
        </div>,
        portalTarget,
      )}
    </>
  );
}
