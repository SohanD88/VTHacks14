import type { ScaleCalibration } from "../types";

export function calibrationFactor(reference?: ScaleCalibration | null): number {
  if (!reference) return 1;
  const [a, b] = reference.reference_points;
  return reference.distance_m / Math.hypot(...a.map((v, i) => v - b[i]));
}
