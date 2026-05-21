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
  createWorldTerrainAsync,
  Math as CesiumMath,
  Rectangle,
  ScreenSpaceEventType,
  UrlTemplateImageryProvider,
  type Viewer as CesiumViewer,
} from "cesium";
import type { SelectedLocation, SavedLocationMarker } from "@/types/map";

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

const DOMAIN_FILL_COLOR = Color.fromCssColorString("#3b82f6").withAlpha(0.08);
const DOMAIN_OUTLINE_COLOR = Color.fromCssColorString("#3b82f6");
const PIN_COLOR = Color.fromCssColorString("#3b82f6");
const SAVED_COLOR = Color.fromCssColorString("#3b82f6").withAlpha(0.6);

const terrainProvider = createWorldTerrainAsync();

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

    // Dev-only: Expose the viewer to the window for debugging
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
            50,
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
          position={Cartesian3.fromDegrees(loc.longitude, loc.latitude, 20)}
          name={loc.label ?? undefined}
        >
          <PointGraphics
            pixelSize={10}
            color={SAVED_COLOR}
            outlineColor={Color.WHITE}
            outlineWidth={2}
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

function buildDomainRectangle(
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
