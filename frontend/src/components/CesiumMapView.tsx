import { useCallback, useMemo, useRef } from "react";
import {
  Viewer,
  Entity,
  RectangleGraphics,
  PointGraphics,
  BillboardGraphics,
  ScreenSpaceEventHandler,
  ScreenSpaceEvent,
} from "resium";
import {
  Cartesian3,
  Cartographic,
  Color,
  createWorldTerrainAsync,
  Ion,
  Math as CesiumMath,
  Rectangle,
  ScreenSpaceEventType,
  type Viewer as CesiumViewer,
} from "cesium";
import type { SelectedLocation, SavedLocationMarker } from "@/types/map";

interface CesiumMapViewProps {
  selectedLocation: SelectedLocation | null;
  onLocationSelect: (location: SelectedLocation) => void;
  domainSizeKm?: number;
  savedLocations?: SavedLocationMarker[];
}

const INITIAL_DESTINATION = Cartesian3.fromDegrees(-105.78, 39.75, 40_000);
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

  const handleClick = useCallback(
    (event: { position: { x: number; y: number } }) => {
      const viewer = viewerRef.current;
      if (!viewer) return;

      const cartesian = viewer.scene.pickPosition(event.position);
      if (!cartesian) {
        const ray = viewer.camera.getPickRay(event.position);
        if (!ray) return;
        const globeCartesian = viewer.scene.globe.pick(ray, viewer.scene);
        if (!globeCartesian) return;
        const carto = Cartographic.fromCartesian(globeCartesian);
        onLocationSelect({
          latitude: CesiumMath.toDegrees(carto.latitude),
          longitude: CesiumMath.toDegrees(carto.longitude),
        });
        return;
      }

      const carto = Cartographic.fromCartesian(cartesian);
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
      style={{ cursor: "crosshair" }}
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

CesiumMapView.flyToInitial = function flyToInitial(viewer: CesiumViewer) {
  viewer.camera.flyTo({
    destination: INITIAL_DESTINATION,
    orientation: INITIAL_ORIENTATION,
    duration: 0,
  });
};

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
