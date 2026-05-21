export interface SelectedLocation {
  latitude: number;
  longitude: number;
}

export interface SavedLocationMarker {
  id: string;
  latitude: number;
  longitude: number;
  label: string | null;
}
