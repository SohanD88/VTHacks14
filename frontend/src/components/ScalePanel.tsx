import { useState } from "react";
import type { ScaleCalibration, Scene, Vector3 } from "../types";
import { calibrationFactor } from "../services/calibration";

interface Props {
  scene: Scene;
  points: Vector3[];
  picking: boolean;
  busy: boolean;
  onPick(): void;
  onCancel(): void;
  onApply(reference: ScaleCalibration | null): void;
}

export function ScalePanel({
  scene,
  points,
  picking,
  busy,
  onPick,
  onCancel,
  onApply,
}: Props) {
  const [width, setWidth] = useState("3.5");
  const [basis, setBasis] = useState<ScaleCalibration["basis"]>("assumed");
  const span =
    points.length === 2
      ? Math.hypot(...points[0].map((v, i) => v - points[1][i]))
      : 0;
  const meters = Number(width) * 0.3048;
  const factor = calibrationFactor(scene.calibration);
  const correction = meters / span;
  const total = correction * factor;
  const valid =
    span / factor >= 0.01 &&
    Number.isFinite(total) &&
    meters > 0 &&
    meters <= 1000 &&
    total >= 0.05 &&
    total <= 20;
  return (
    <details className="scale-panel">
      <summary>Room scale</summary>
      <p className="input-meta" data-testid="scale-status">
        {scene.calibration
          ? scene.scale_note
          : "Dimensions use estimated video depth. No reference width applied."}
      </p>
      <p className="input-meta">
        Mark the two inner sides of one doorway at the same height. The default
        width is an assumption, not a measurement.
      </p>
      <fieldset disabled={busy}>
        <legend className="visually-hidden">Doorway scale reference</legend>
        <div className="editor-toolbar">
          <button onClick={onPick} aria-pressed={picking}>
            Pick doorway width
          </button>
          {(picking || points.length > 0) && (
            <button onClick={onCancel}>Cancel reference</button>
          )}
        </div>
        <p
          className="input-meta"
          aria-live="polite"
          data-testid="reference-progress"
        >
          {picking
            ? `Click ${points.length ? "the second" : "the first"} inner doorway edge in the model. You can orbit between clicks.`
            : points.length === 2
              ? "Two reference points selected. Check the line before applying."
              : "Select two visible points to set the room scale."}
        </p>
        <label>
          Reference width (feet)
          <input
            type="number"
            min="0.1"
            max="100"
            step="0.1"
            value={width}
            onChange={(e) => setWidth(e.target.value)}
          />
        </label>
        <label>
          Reference basis
          <select
            value={basis}
            onChange={(e) =>
              setBasis(e.target.value as ScaleCalibration["basis"])
            }
          >
            <option value="assumed">Assumed doorway width</option>
            <option value="measured">I measured this width</option>
          </select>
        </label>
        {points.length === 2 && (
          <p className="input-meta">
            Selected span: {span.toFixed(3)} estimated m.{" "}
            {valid
              ? `Apply ${correction.toFixed(3)}× to the entire room (${meters.toFixed(4)} m reference).`
              : "Check the width or choose points farther apart; this scale correction is outside supported limits."}
          </p>
        )}
        <button
          className="primary-action"
          disabled={!valid || picking}
          onClick={() =>
            onApply({
              reference_points: points.map((p) => p.map((v) => v / factor)) as [
                Vector3,
                Vector3,
              ],
              distance_m: meters,
              basis,
            })
          }
        >
          Apply room scale
        </button>
        {scene.calibration && (
          <button onClick={() => onApply(null)}>Remove scale reference</button>
        )}
      </fieldset>
      <p className="input-meta">
        Scales the room and camera path together. It does not correct warped
        geometry. Undo and Reset scene are available.
      </p>
    </details>
  );
}
