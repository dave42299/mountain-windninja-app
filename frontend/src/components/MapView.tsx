import { useCallback, useMemo, useState } from "react";
import MapGL, {
  Layer,
  Marker,
  NavigationControl,
  Source,
  type MapLayerMouseEvent,
} from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapPin } from "lucide-react";

export interface SelectedLocation {
  latitude: number;
  longitude: number;
}

interface MapViewProps {
  selectedLocation: SelectedLocation | null;
  onLocationSelect: (location: SelectedLocation) => void;
  domainSizeKm?: number;
}

const INITIAL_VIEW = {
  longitude: -105.78,
  latitude: 39.75,
  zoom: 8,
  pitch: 45,
};

const MAP_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

export default function MapView({
  selectedLocation,
  onLocationSelect,
  domainSizeKm,
}: MapViewProps) {
  const [viewState, setViewState] = useState(INITIAL_VIEW);

  const handleClick = useCallback(
    (event: MapLayerMouseEvent) => {
      const { lng, lat } = event.lngLat;
      onLocationSelect({ latitude: lat, longitude: lng });
    },
    [onLocationSelect],
  );

  const domainGeoJson = useMemo(() => {
    if (!selectedLocation || !domainSizeKm) return null;
    return buildDomainSquare(
      selectedLocation.latitude,
      selectedLocation.longitude,
      domainSizeKm,
    );
  }, [selectedLocation, domainSizeKm]);

  return (
    <MapGL
      {...viewState}
      onMove={(evt) => setViewState(evt.viewState)}
      onClick={handleClick}
      style={{ width: "100%", height: "100%" }}
      mapStyle={MAP_STYLE}
      cursor="crosshair"
    >
      <NavigationControl position="top-right" />

      {selectedLocation && (
        <Marker
          latitude={selectedLocation.latitude}
          longitude={selectedLocation.longitude}
          anchor="bottom"
        >
          <MapPin className="h-8 w-8 text-primary drop-shadow-md" />
        </Marker>
      )}

      {domainGeoJson && (
        <Source id="domain-extent" type="geojson" data={domainGeoJson}>
          <Layer
            id="domain-extent-fill"
            type="fill"
            paint={{
              "fill-color": "#3b82f6",
              "fill-opacity": 0.08,
            }}
          />
          <Layer
            id="domain-extent-line"
            type="line"
            paint={{
              "line-color": "#3b82f6",
              "line-width": 2,
              "line-dasharray": [4, 2],
            }}
          />
        </Source>
      )}
    </MapGL>
  );
}

function buildDomainSquare(
  latitude: number,
  longitude: number,
  sizeKm: number,
): GeoJSON.Feature<GeoJSON.Polygon> {
  const halfKm = sizeKm / 2;
  const latDelta = halfKm / 111.32;
  const lonDelta = halfKm / (111.32 * Math.cos((latitude * Math.PI) / 180));

  const north = latitude + latDelta;
  const south = latitude - latDelta;
  const east = longitude + lonDelta;
  const west = longitude - lonDelta;

  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [west, north],
          [east, north],
          [east, south],
          [west, south],
          [west, north],
        ],
      ],
    },
  };
}
