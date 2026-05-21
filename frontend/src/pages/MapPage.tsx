import { useState } from "react";
import MapView, { type SelectedLocation } from "@/components/MapView";
import ForecastForm from "@/components/ForecastForm";
import ForecastSidebar from "@/components/ForecastSidebar";
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

  const handleLocationSelect = (location: SelectedLocation) => {
    setSelectedLocation(location);
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
