import { useMemo, useRef, useCallback } from "react";
import { Viewer, Entity, RectangleGraphics, PointGraphics } from "resium";
import {
  Cartesian3,
  Color,
  HeightReference,
  Math as CesiumMath,
  type Viewer as CesiumViewer,
} from "cesium";
import {
  terrainProvider,
  buildDomainRectangle,
  DOMAIN_FILL_COLOR,
  DOMAIN_OUTLINE_COLOR,
  PIN_COLOR,
} from "@/lib/cesium-utils";

interface CesiumDetailMapProps {
  latitude: number;
  longitude: number;
  sizeKm: number;
  onViewerReady?: (viewer: CesiumViewer | null) => void;
}

export default function CesiumDetailMap({
  latitude,
  longitude,
  sizeKm,
  onViewerReady,
}: CesiumDetailMapProps) {
  const viewerRef = useRef<CesiumViewer>(null);

  const viewerCallback = useCallback(
    (viewer: CesiumViewer | null) => {
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

      onViewerReady?.(viewer);
    },
    [latitude, longitude, onViewerReady],
  );

  const pinPosition = useMemo(
    () => Cartesian3.fromDegrees(longitude, latitude),
    [latitude, longitude],
  );

  const domainRectangle = useMemo(
    () => buildDomainRectangle(latitude, longitude, sizeKm),
    [latitude, longitude, sizeKm],
  );

  return (
    <Viewer
      ref={(ref) => {
        (viewerRef as React.MutableRefObject<CesiumViewer | null>).current =
          ref?.cesiumElement ?? null;
        viewerCallback(ref?.cesiumElement ?? null);
      }}
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
      style={{ width: "100%", height: "100%" }}
    >
      <Entity position={pinPosition} name="Forecast location">
        <PointGraphics
          pixelSize={12}
          color={PIN_COLOR}
          outlineColor={Color.WHITE}
          outlineWidth={2}
          heightReference={HeightReference.CLAMP_TO_GROUND}
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
