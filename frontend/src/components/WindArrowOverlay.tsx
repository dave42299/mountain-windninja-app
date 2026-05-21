import { useEffect, useRef, useCallback } from "react";
import {
  Cartesian3,
  PolylineCollection,
  Material,
  type Viewer as CesiumViewer,
} from "cesium";
import type { WindFieldResponse } from "@/api/types";
import {
  buildArrowsFromWindField,
  buildArrowheadPositions,
  computeSubsampleStep,
} from "@/lib/wind-arrows";

interface WindArrowOverlayProps {
  viewer: CesiumViewer | null;
  windData: WindFieldResponse | null;
  visible?: boolean;
  altitudeOffset?: number;
}

export default function WindArrowOverlay({
  viewer,
  windData,
  visible = true,
  altitudeOffset = 30,
}: WindArrowOverlayProps) {
  const polylineCollectionRef = useRef<PolylineCollection | null>(null);
  const cameraListenerRef = useRef<(() => void) | null>(null);
  const lastStepRef = useRef<number>(-1);

  const rebuildArrows = useCallback(
    (step: number) => {
      if (!viewer || !windData) return;

      if (polylineCollectionRef.current) {
        viewer.scene.primitives.remove(polylineCollectionRef.current);
        polylineCollectionRef.current = null;
      }

      const collection = new PolylineCollection();
      const arrows = buildArrowsFromWindField(windData, step);

      for (const arrow of arrows) {
        const startPos = Cartesian3.fromDegrees(
          arrow.startLon,
          arrow.startLat,
          altitudeOffset,
        );
        const endPos = Cartesian3.fromDegrees(
          arrow.endLon,
          arrow.endLat,
          altitudeOffset,
        );

        collection.add({
          positions: [startPos, endPos],
          width: 2.5,
          material: Material.fromType("Color", {
            color: arrow.color,
          }),
        });

        const headPositions = buildArrowheadPositions(
          arrow.startLon,
          arrow.startLat,
          arrow.endLon,
          arrow.endLat,
          altitudeOffset,
        );
        if (headPositions.length === 3) {
          collection.add({
            positions: headPositions,
            width: 2.5,
            material: Material.fromType("Color", {
              color: arrow.color,
            }),
          });
        }
      }

      collection.show = visible;
      viewer.scene.primitives.add(collection);
      polylineCollectionRef.current = collection;
      lastStepRef.current = step;
    },
    [viewer, windData, altitudeOffset, visible],
  );

  useEffect(() => {
    if (!viewer || !windData) return;

    const previousPercentageChanged = viewer.camera.percentageChanged;
    viewer.camera.percentageChanged = 0.1;

    const cameraAltitude =
      viewer.camera.positionCartographic.height;
    const initialStep = computeSubsampleStep(cameraAltitude);
    rebuildArrows(initialStep);

    const onCameraChange = () => {
      const altitude = viewer.camera.positionCartographic.height;
      const newStep = computeSubsampleStep(altitude);
      if (newStep !== lastStepRef.current) {
        rebuildArrows(newStep);
      }
    };

    const removeListener = viewer.camera.changed.addEventListener(onCameraChange);
    cameraListenerRef.current = removeListener;

    return () => {
      if (cameraListenerRef.current) {
        cameraListenerRef.current();
        cameraListenerRef.current = null;
      }
      if (polylineCollectionRef.current && viewer.scene) {
        viewer.scene.primitives.remove(polylineCollectionRef.current);
        polylineCollectionRef.current = null;
      }
      viewer.camera.percentageChanged = previousPercentageChanged;
    };
  }, [viewer, windData, rebuildArrows]);

  useEffect(() => {
    if (polylineCollectionRef.current) {
      polylineCollectionRef.current.show = visible;
    }
  }, [visible]);

  return null;
}
