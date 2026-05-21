import { useState } from "react";
import { Bookmark, MapPin, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import {
  useForecastAreas,
  useCreateForecastArea,
  useDeleteForecastArea,
} from "@/hooks/use-forecast-areas";
import type { SelectedLocation } from "@/types/map";
import type { ForecastAreaResponse } from "@/api/types";

interface SavedLocationsProps {
  onSelectLocation: (location: SelectedLocation, sizeKm: number) => void;
}

export default function SavedLocations({
  onSelectLocation,
}: SavedLocationsProps) {
  const { data: areas, isLoading } = useForecastAreas();
  const deleteArea = useDeleteForecastArea();
  const [deleteTarget, setDeleteTarget] = useState<ForecastAreaResponse | null>(
    null,
  );

  const handleSelect = (area: ForecastAreaResponse) => {
    onSelectLocation(
      { latitude: area.center_latitude, longitude: area.center_longitude },
      area.size_km,
    );
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteArea.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast.success("Location deleted");
        setDeleteTarget(null);
      },
      onError: (error) => {
        toast.error("Failed to delete location", {
          description: error.message,
        });
      },
    });
  };

  if (isLoading) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">Loading...</div>
    );
  }

  if (!areas || areas.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">
        No saved locations yet
      </div>
    );
  }

  return (
    <>
      <div className="max-h-48 overflow-y-auto">
        {areas.map((area) => (
          <div
            key={area.id}
            className="flex items-center gap-1 border-b px-2 py-1.5 last:border-0"
          >
            <button
              onClick={() => handleSelect(area)}
              className="flex flex-1 items-center gap-2 rounded px-1 py-0.5 text-left transition-colors hover:bg-accent"
            >
              <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">
                  {area.label ?? `${area.center_latitude.toFixed(3)}, ${area.center_longitude.toFixed(3)}`}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {area.size_km} km
                </p>
              </div>
            </button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
              onClick={() => setDeleteTarget(area)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete saved location?</DialogTitle>
            <DialogDescription>
              This will remove &ldquo;
              {deleteTarget?.label ??
                `${deleteTarget?.center_latitude.toFixed(3)}, ${deleteTarget?.center_longitude.toFixed(3)}`}
              &rdquo; from your saved locations. Existing forecasts will not be
              affected.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteArea.isPending}
            >
              {deleteArea.isPending ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface SaveLocationButtonProps {
  latitude: number;
  longitude: number;
  sizeKm: number;
}

export function SaveLocationButton({
  latitude,
  longitude,
  sizeKm,
}: SaveLocationButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [label, setLabel] = useState("");
  const createArea = useCreateForecastArea();

  const handleSave = () => {
    createArea.mutate(
      {
        center_latitude: latitude,
        center_longitude: longitude,
        size_km: sizeKm,
        label: label.trim() || undefined,
      },
      {
        onSuccess: () => {
          toast.success("Location saved");
          setIsOpen(false);
          setLabel("");
        },
        onError: (error) => {
          toast.error("Failed to save location", {
            description: error.message,
          });
        },
      },
    );
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Bookmark className="h-3.5 w-3.5" />
          Save location
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save this location</DialogTitle>
          <DialogDescription>
            {latitude.toFixed(5)}, {longitude.toFixed(5)} &middot; {sizeKm} km
          </DialogDescription>
        </DialogHeader>
        <div>
          <Input
            placeholder="Label (optional)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSave()}
          />
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={handleSave} disabled={createArea.isPending}>
            {createArea.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
