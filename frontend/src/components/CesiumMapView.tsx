import { useCallback, useMemo, useRef } from "react";
import {
  Viewer,
  Entity,
  RectangleGraphics,
  PointGraphics,
  ScreenSpaceEventHandler,
  ScreenSpaceEvent,
} from "resium";
import {
  Cartesian2,
  Cartesian3,
  Cartographic,
  Color,
  HeightReference,
  Math as CesiumMath,
  ScreenSpaceEventType,
  UrlTemplateImageryProvider,
  type Viewer as CesiumViewer,
} from "cesium";
import type { SelectedLocation, SavedLocationMarker } from "@/types/map";
import {
  terrainProvider,
  buildDomainRectangle,
  DOMAIN_FILL_COLOR,
  DOMAIN_OUTLINE_COLOR,
  PIN_COLOR,
  SAVED_MARKER_COLOR,
} from "@/lib/cesium-utils";

interface CesiumMapViewProps {
  selectedLocation: SelectedLocation | null;
  onLocationSelect: (location: SelectedLocation) => void;
  domainSizeKm?: number;
  savedLocations?: SavedLocationMarker[];
}

const INITIAL_DESTINATION = Cartesian3.fromDegrees(-106.013, 39.168, 44_414);
const INITIAL_ORIENTATION = {
  heading: CesiumMath.toRadians(0),
  pitch: CesiumMath.toRadians(-45),
  roll: 0,
};

export default function CesiumMapView({
  selectedLocation,
  onLocationSelect,
  domainSizeKm,
  savedLocations = [],
}: CesiumMapViewProps) {
  const viewerRef = useRef<CesiumViewer>(null);
  const hasInitialized = useRef(false);

  const viewerCallback = useCallback((viewer: CesiumViewer | null) => {
    if (!viewer || hasInitialized.current) return;
    hasInitialized.current = true;

    if (import.meta.env.DEV) {
      (window as unknown as Record<string, unknown>).__cesiumViewer = viewer;
    }

    viewer.camera.setView({
      destination: INITIAL_DESTINATION,
      orientation: INITIAL_ORIENTATION,
    });

    const labelsOverlay = new UrlTemplateImageryProvider({
      url: "https://basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}@2x.png",
      credit: "CartoDB",
    });
    viewer.imageryLayers.addImageryProvider(labelsOverlay);
  }, []);

  const handleClick = useCallback(
    (
      event:
        | { position: Cartesian2 }
        | { startPosition: Cartesian2; endPosition: Cartesian2 },
    ) => {
      if (!("position" in event)) return;
      const viewer = viewerRef.current;
      if (!viewer) return;

      const ray = viewer.camera.getPickRay(event.position);
      if (!ray) return;
      const globeCartesian = viewer.scene.globe.pick(ray, viewer.scene);
      if (!globeCartesian) return;

      const carto = Cartographic.fromCartesian(globeCartesian);
      onLocationSelect({
        latitude: CesiumMath.toDegrees(carto.latitude),
        longitude: CesiumMath.toDegrees(carto.longitude),
      });
    },
    [onLocationSelect],
  );

  const domainRectangle = useMemo(() => {
    if (!selectedLocation || !domainSizeKm) return null;
    return buildDomainRectangle(
      selectedLocation.latitude,
      selectedLocation.longitude,
      domainSizeKm,
    );
  }, [selectedLocation, domainSizeKm]);

  const pinPosition = useMemo(
    () =>
      selectedLocation
        ? Cartesian3.fromDegrees(
            selectedLocation.longitude,
            selectedLocation.latitude,
          )
        : null,
    [selectedLocation],
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
      style={{ width: "100%", height: "100%", cursor: "crosshair" }}
    >
      <ScreenSpaceEventHandler>
        <ScreenSpaceEvent
          action={handleClick}
          type={ScreenSpaceEventType.LEFT_CLICK}
        />
      </ScreenSpaceEventHandler>

      {savedLocations.map((loc) => (
        <Entity
          key={loc.id}
          position={Cartesian3.fromDegrees(loc.longitude, loc.latitude)}
          name={loc.label ?? undefined}
        >
          <PointGraphics
            pixelSize={10}
            color={SAVED_MARKER_COLOR}
            outlineColor={Color.WHITE}
            outlineWidth={2}
            heightReference={HeightReference.CLAMP_TO_GROUND}
          />
        </Entity>
      ))}

      {pinPosition && (
        <Entity position={pinPosition} name="Selected location">
          <PointGraphics
            pixelSize={14}
            color={PIN_COLOR}
            outlineColor={Color.WHITE}
            outlineWidth={3}
            heightReference={HeightReference.CLAMP_TO_GROUND}
          />
        </Entity>
      )}

      {domainRectangle && (
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
      )}
    </Viewer>
  );
}
