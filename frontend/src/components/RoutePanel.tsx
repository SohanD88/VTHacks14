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
    <section className="route-panel" aria-label="Pathfinder">
      <div className="route-intro">
        <span className="route-badge">Single-floor routing</span>
        <h3>Where do you want to go?</h3>
        <p>
          Choose two places. Pathfinder finds a route around the obstacles in
          your saved model.
        </p>
      </div>
      <fieldset disabled={disabled}>
        <legend className="visually-hidden">Route points</legend>
        {(["start", "end"] as const).map((which, index) => {
          const endpoint = route[which];
          const title = which === "start" ? "Start" : "Destination";
          return (
            <div
              key={which}
              className={`route-endpoint route-endpoint-${which}`}
            >
              <label>
                <span className="route-step">
                  <span aria-hidden="true">{index + 1}</span>
                  {title}
                </span>
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
                  <option value="">
                    {doors.length
                      ? "Choose a doorway…"
                      : "Pick a point in the model"}
                  </option>
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
                className="route-pick"
                aria-pressed={route.picking === which}
                onClick={() => onPick(which)}
              >
                Pick {title.toLowerCase()} in model{" "}
                <span aria-hidden="true">↗</span>
              </button>
              {endpoint?.point && (
                <p className="route-coordinates">
                  XYZ · {endpoint.point.map((v) => v.toFixed(2)).join(" / ")} m
                </p>
              )}
            </div>
          );
        })}
        <div className="route-actions">
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
        <div className="route-picking" role="status">
          <strong>
            Choose your{" "}
            {route.picking === "start" ? "starting point" : "destination"}
          </strong>
          <p>
            Click a floor surface or doorway in the model. You can still drag to
            orbit.
          </p>
          <button onClick={route.cancelPick}>Cancel point selection</button>
        </div>
      )}
      {route.error && (
        <div role="alert" className="route-error">
          <strong>We couldn’t plan this route</strong>
          <p>{route.error}</p>
        </div>
      )}
      {route.result ? (
        <section
          className="route-explanation"
          role="status"
          data-testid="route-result"
          aria-label="Route explanation"
        >
          <span className="route-badge">Estimated path</span>
          <div className="route-distance">
            {route.result.distance_m.toFixed(2)} <span>meters</span>
          </div>
          <div className="route-metrics">
            <span>
              Obstacle clearance
              <strong>{Math.round(route.result.clearance_m * 100)} cm</strong>
            </span>
            <span>
              Floor coverage<strong>Single level</strong>
            </span>
          </div>
          <h3>How this path was planned</h3>
          <ol>
            <li>
              <strong>Follow the modeled floor.</strong> The planner searches
              the saved floor geometry for the shortest available grid route.
            </li>
            <li>
              <strong>Go around obstacles.</strong> Walls and furniture block
              the route, with {Math.round(route.result.clearance_m * 100)} cm of
              clearance. Missing floor sections are excluded.
            </li>
            <li>
              <strong>
                {route.result.start.object_id || route.result.end.object_id
                  ? "Use a clear doorway approach."
                  : "Connect the selected areas."}
              </strong>{" "}
              {route.result.start.object_id || route.result.end.object_id
                ? "Doorway markers sit on nearby reachable floor. They do not confirm that a door is open."
                : "Floor points snap to the routing grid; markers show the resolved endpoints."}
            </li>
          </ol>
          <div className="route-legend">
            <span>
              <i /> Start
            </span>
            <span>
              <i /> Destination
            </span>
          </div>
          <details className="route-limits">
            <summary>Model limits & uncertainties</summary>
            {route.result.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </details>
        </section>
      ) : (
        !route.picking && (
          <div className="route-empty">
            <strong>
              {route.busy
                ? "Checking the modeled floor…"
                : "Your route will appear here"}
            </strong>
            <p>
              {route.busy
                ? "Finding a connection around walls and furniture."
                : "Select a start and destination, then choose Find path to see the distance and how it was planned."}
            </p>
          </div>
        )
      )}
      <p className="route-disclaimer">
        Paths are estimates from the model. Real-world access and hazards are
        unverified.
      </p>
    </section>
  );
}
