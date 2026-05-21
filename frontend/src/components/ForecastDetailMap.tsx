import { useMemo } from "react";
import MapGL, { Layer, Marker, Source } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapPin } from "lucide-react";

const MAP_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

interface ForecastDetailMapProps {
  latitude: number;
  longitude: number;
  sizeKm: number;
}

export default function ForecastDetailMap({
  latitude,
  longitude,
  sizeKm,
}: ForecastDetailMapProps) {
  const domainGeoJson = useMemo(
    () => buildDomainSquare(latitude, longitude, sizeKm),
    [latitude, longitude, sizeKm],
  );

  return (
    <MapGL
      initialViewState={{
        longitude,
        latitude,
        zoom: 10,
      }}
      style={{ width: "100%", height: "100%" }}
      mapStyle={MAP_STYLE}
      interactive={false}
    >
      <Marker latitude={latitude} longitude={longitude} anchor="bottom">
        <MapPin className="h-6 w-6 text-primary" />
      </Marker>

      <Source id="domain-extent" type="geojson" data={domainGeoJson}>
        <Layer
          id="domain-extent-fill"
          type="fill"
          paint={{ "fill-color": "#3b82f6", "fill-opacity": 0.08 }}
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
