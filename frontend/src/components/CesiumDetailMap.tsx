import { useMemo, useRef, useEffect } from "react";
import { Viewer, Entity, RectangleGraphics, PointGraphics } from "resium";
import {
  Cartesian3,
  Color,
  createWorldTerrainAsync,
  Math as CesiumMath,
  Rectangle,
  type Viewer as CesiumViewer,
} from "cesium";

interface CesiumDetailMapProps {
  latitude: number;
  longitude: number;
  sizeKm: number;
}

const DOMAIN_FILL_COLOR = Color.fromCssColorString("#3b82f6").withAlpha(0.08);
const DOMAIN_OUTLINE_COLOR = Color.fromCssColorString("#3b82f6");
const PIN_COLOR = Color.fromCssColorString("#3b82f6");

const terrainProvider = createWorldTerrainAsync();

export default function CesiumDetailMap({
  latitude,
  longitude,
  sizeKm,
}: CesiumDetailMapProps) {
  const viewerRef = useRef<CesiumViewer>(null);

  const pinPosition = useMemo(
    () => Cartesian3.fromDegrees(longitude, latitude, 20),
    [latitude, longitude],
  );

  const domainRectangle = useMemo(() => {
    const halfKm = sizeKm / 2;
    const latDelta = halfKm / 111.32;
    const lonDelta = halfKm / (111.32 * Math.cos((latitude * Math.PI) / 180));
    return Rectangle.fromDegrees(
      longitude - lonDelta,
      latitude - latDelta,
      longitude + lonDelta,
      latitude + latDelta,
    );
  }, [latitude, longitude, sizeKm]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    viewer.camera.flyTo({
      destination: Cartesian3.fromDegrees(longitude, latitude, 30_000),
      orientation: {
        heading: 0,
        pitch: CesiumMath.toRadians(-90),
        roll: 0,
      },
      duration: 0,
    });
  }, [latitude, longitude]);

  return (
    <Viewer
      ref={viewerRef}
      full
      terrainProvider={terrainProvider}
      timeline={false}
      animation={false}
      homeButton={false}
      sceneModePicker={false}
      baseLayerPicker={false}
      geocoder={false}
      navigationHelpButton={false}
      fullscreenButton={false}
      infoBox={false}
      selectionIndicator={false}
      scene3DOnly
    >
      <Entity position={pinPosition} name="Forecast location">
        <PointGraphics
          pixelSize={12}
          color={PIN_COLOR}
          outlineColor={Color.WHITE}
          outlineWidth={2}
        />
      </Entity>

      <Entity>
        <RectangleGraphics
          coordinates={domainRectangle}
          material={DOMAIN_FILL_COLOR}
          outline
          outlineColor={DOMAIN_OUTLINE_COLOR}
          outlineWidth={2}
          height={0}
        />
      </Entity>
    </Viewer>
  );
}
