import { Cartesian3, Color, Math as CesiumMath } from "cesium";
import type { WindFieldResponse } from "@/api/types";

export interface ArrowData {
  startLon: number;
  startLat: number;
  endLon: number;
  endLat: number;
  speed: number;
  color: Color;
}

const SPEED_COLORS: [number, Color][] = [
  [0.0, Color.fromCssColorString("#3b82f6")],
  [0.2, Color.fromCssColorString("#22d3ee")],
  [0.4, Color.fromCssColorString("#22c55e")],
  [0.6, Color.fromCssColorString("#eab308")],
  [0.8, Color.fromCssColorString("#f97316")],
  [1.0, Color.fromCssColorString("#ef4444")],
];

export function colorForNormalizedSpeed(t: number): Color {
  const clamped = Math.max(0, Math.min(1, t));

  for (let i = 1; i < SPEED_COLORS.length; i++) {
    const [threshold, color] = SPEED_COLORS[i];
    const [prevThreshold, prevColor] = SPEED_COLORS[i - 1];
    if (clamped <= threshold) {
      const localT = (clamped - prevThreshold) / (threshold - prevThreshold);
      return Color.lerp(prevColor, color, localT, new Color());
    }
  }
  return SPEED_COLORS[SPEED_COLORS.length - 1][1].clone();
}

export function computeSubsampleStep(cameraAltitude: number): number {
  if (cameraAltitude > 25_000) return 8;
  if (cameraAltitude > 15_000) return 4;
  if (cameraAltitude > 10_000) return 3;
  if (cameraAltitude > 5_000) return 2;
  return 1;
}

const BASE_ARROW_LENGTH_DEG = 0.003;

export function buildArrowsFromWindField(
  windData: WindFieldResponse,
  step: number,
): ArrowData[] {
  const { u, v, width, height, bounds, speed_max } = windData;

  const lonSpan = bounds.east - bounds.west;
  const latSpan = bounds.north - bounds.south;
  const cellLonSize = lonSpan / width;
  const cellLatSize = latSpan / height;

  const effectiveMax = speed_max > 0 ? speed_max : 1;
  const arrowScale = BASE_ARROW_LENGTH_DEG * Math.max(step, 1);

  const arrows: ArrowData[] = [];

  for (let row = 0; row < height; row += step) {
    for (let col = 0; col < width; col += step) {
      const idx = row * width + col;
      const uVal = u[idx];
      const vVal = v[idx];

      const speed = Math.sqrt(uVal * uVal + vVal * vVal);
      if (speed < 0.1) continue;

      const normalizedSpeed = speed / effectiveMax;

      const startLon = bounds.west + (col + 0.5) * cellLonSize;
      const startLat = bounds.north - (row + 0.5) * cellLatSize;

      const direction = Math.atan2(uVal, vVal);
      const arrowLength = arrowScale * normalizedSpeed;

      const endLon = startLon + arrowLength * Math.sin(direction);
      const endLat = startLat + arrowLength * Math.cos(direction);

      arrows.push({
        startLon,
        startLat,
        endLon,
        endLat,
        speed,
        color: colorForNormalizedSpeed(normalizedSpeed),
      });
    }
  }

  return arrows;
}

const ARROWHEAD_ANGLE = CesiumMath.toRadians(25);
const ARROWHEAD_FRACTION = 0.3;

export function buildArrowheadPositions(
  startLon: number,
  startLat: number,
  endLon: number,
  endLat: number,
  altitudeOffset: number,
): Cartesian3[] {
  const dx = endLon - startLon;
  const dy = endLat - startLat;
  const length = Math.sqrt(dx * dx + dy * dy);
  if (length === 0) return [];

  const headLength = length * ARROWHEAD_FRACTION;
  const angle = Math.atan2(dy, dx);

  const leftAngle = angle + Math.PI - ARROWHEAD_ANGLE;
  const rightAngle = angle + Math.PI + ARROWHEAD_ANGLE;

  const leftLon = endLon + headLength * Math.cos(leftAngle);
  const leftLat = endLat + headLength * Math.sin(leftAngle);
  const rightLon = endLon + headLength * Math.cos(rightAngle);
  const rightLat = endLat + headLength * Math.sin(rightAngle);

  return [
    Cartesian3.fromDegrees(leftLon, leftLat, altitudeOffset),
    Cartesian3.fromDegrees(endLon, endLat, altitudeOffset),
    Cartesian3.fromDegrees(rightLon, rightLat, altitudeOffset),
  ];
}
