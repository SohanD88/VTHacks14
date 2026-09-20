import type { Scene } from "../types";
import type { useSceneRoute } from "../hooks/useSceneRoute";

interface Props {
  scene: Scene;
  route: ReturnType<typeof useSceneRoute>;
  disabled: boolean;
  onPick(which: "start" | "end"): void;
}

export function RoutePanel({ scene, route, disabled, onPick }: Props) {
  const doors = scene.objects.filter(
    (o) =>
      !o.deleted &&
      (o.entrance ||
        ["door", "doorway", "entrance", "exit", "opening"].includes(o.kind)),
  );
  return (
    <details open className="route-panel">
      <summary>Pathfinder</summary>
      <p className="input-meta">
        Choose floor points in the model or doorway destinations. Paths follow
        the saved scene.
      </p>
      <fieldset disabled={disabled}>
        <legend>Route points</legend>
        {(["start", "end"] as const).map((which) => {
          const endpoint = route[which];
          const title = which === "start" ? "Start" : "Destination";
          return (
            <div key={which}>
              <label>
                {title}
                <select
                  aria-label={`Route ${which}`}
                  value={
                    endpoint?.object_id ?? (endpoint?.point ? "point" : "")
                  }
                  onChange={(event) =>
                    route.choose(
                      which,
                      event.target.value
                        ? { object_id: event.target.value }
                        : undefined,
                    )
                  }
                >
                  <option value="">Choose a doorway or pick a point</option>
                  {endpoint?.point && (
                    <option value="point" disabled>
                      Picked floor point
                    </option>
                  )}
                  {doors.map((door) => (
                    <option key={door.id} value={door.id}>
                      {door.label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                aria-pressed={route.picking === which}
                onClick={() => onPick(which)}
              >
                Pick {title.toLowerCase()} in model
              </button>
              {endpoint?.point && (
                <p className="input-meta">
                  {endpoint.point.map((v) => v.toFixed(2)).join(", ")} m
                </p>
              )}
            </div>
          );
        })}
        <div className="editor-toolbar">
          <button
            className="primary-action"
            disabled={!route.start || !route.end || route.busy}
            onClick={() => void route.calculate()}
          >
            {route.busy ? "Finding path…" : "Find path"}
          </button>
          <button
            onClick={route.clear}
            disabled={!route.start && !route.end && !route.picking}
          >
            Clear path
          </button>
        </div>
      </fieldset>
      {route.picking && (
        <p role="status">
          Click a floor or doorway for the{" "}
          {route.picking === "start" ? "start" : "destination"}.{" "}
          <button onClick={route.cancelPick}>Cancel point selection</button>
        </p>
      )}
      {route.error && (
        <p role="alert" className="editor-error">
          {route.error}
        </p>
      )}
      {route.result ? (
        <div role="status" data-testid="route-result">
          <strong>
            Estimated path · {route.result.distance_m.toFixed(2)} m
          </strong>
          <p className="input-meta">
            Green: start. Orange: destination. Clearance from modeled obstacles:{" "}
            {route.result.clearance_m.toFixed(2)} m.
          </p>
          {route.result.warnings.map((warning) => (
            <p className="input-meta" key={warning}>
              {warning}
            </p>
          ))}
        </div>
      ) : (
        <p className="input-meta">
          Single floor only. Distances and access are estimates; doorway
          destinations stop at a clear approach.
        </p>
      )}
    </details>
  );
}
