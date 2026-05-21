import {
  Color,
  createWorldTerrainAsync,
  Rectangle,
} from "cesium";

export const terrainProvider = createWorldTerrainAsync();

export const DOMAIN_FILL_COLOR = Color.fromCssColorString("#3b82f6").withAlpha(0.08);
export const DOMAIN_OUTLINE_COLOR = Color.fromCssColorString("#3b82f6");
export const PIN_COLOR = Color.fromCssColorString("#3b82f6");
export const SAVED_MARKER_COLOR = Color.fromCssColorString("#3b82f6").withAlpha(0.6);

export function buildDomainRectangle(
  latitude: number,
  longitude: number,
  sizeKm: number,
): Rectangle {
  const halfKm = sizeKm / 2;
  const latDelta = halfKm / 111.32;
  const lonDelta = halfKm / (111.32 * Math.cos((latitude * Math.PI) / 180));

  return Rectangle.fromDegrees(
    longitude - lonDelta,
    latitude - latDelta,
    longitude + lonDelta,
    latitude + latDelta,
  );
}
