import { useEffect, useRef } from "react";
import { WindLayer, type WindData } from "cesium-wind-layer";
import type { Viewer as CesiumViewer } from "cesium";
import type { WindFieldResponse } from "@/api/types";

const WIND_COLORS = [
  "#3b82f6", // blue (calm)
  "#22d3ee", // cyan
  "#22c55e", // green
  "#eab308", // yellow
  "#f97316", // orange
  "#ef4444", // red (strong)
];

interface WindOverlayProps {
  viewer: CesiumViewer | null;
  windData: WindFieldResponse | null;
  visible?: boolean;
  particleHeight?: number;
}

function buildWindData(response: WindFieldResponse): WindData {
  return {
    u: {
      array: new Float32Array(response.u),
      min: undefined,
      max: undefined,
    },
    v: {
      array: new Float32Array(response.v),
      min: undefined,
      max: undefined,
    },
    width: response.width,
    height: response.height,
    bounds: response.bounds,
  };
}

export default function WindOverlay({
  viewer,
  windData,
  visible = true,
  particleHeight = 10,
}: WindOverlayProps) {
  const windLayerRef = useRef<WindLayer | null>(null);

  useEffect(() => {
    if (!viewer) return;

    return () => {
      if (windLayerRef.current) {
        windLayerRef.current.destroy();
        windLayerRef.current = null;
      }
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer || !windData) return;

    const data = buildWindData(windData);

    if (windLayerRef.current) {
      windLayerRef.current.updateWindData(data);
    } else {
      windLayerRef.current = new WindLayer(viewer, data, {
        particlesTextureSize: 128,
        particleHeight,
        lineWidth: { min: 1, max: 4 },
        lineLength: { min: 20, max: 100 },
        speedFactor: 4.0,
        dropRate: 0.003,
        dropRateBump: 0.001,
        colors: WIND_COLORS,
        flipY: false,
        useViewerBounds: false,
        dynamic: true,
      });
    }
  }, [viewer, windData, particleHeight]);

  useEffect(() => {
    if (windLayerRef.current) {
      windLayerRef.current.show = visible;
    }
  }, [visible]);

  return null;
}
