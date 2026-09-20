import { useEffect, useRef, useState } from "react";
import type {
  Layers,
  ScanResponse,
  ScaleCalibration,
  Scene,
  SceneObject,
  Transform,
  Vector3,
} from "../types";
import type { LiveCamera } from "../hooks/useLiveCamera";
import { api, API_BASE } from "../services/api";
import { CameraFeed } from "./CameraFeed";
import { ScalePanel } from "./ScalePanel";
import { calibrationFactor } from "../services/calibration";
import { SceneViewer } from "./SceneViewer";
import { RoutePanel } from "./RoutePanel";
import { useSceneRoute } from "../hooks/useSceneRoute";
interface Props {
  camera: LiveCamera;
  active: boolean;
  scan?: ScanResponse;
  onChange(scan: ScanResponse): void;
  onBack(): void;
}
export function Modeler({ camera, active, scan, onChange, onBack }: Props) {
  const [referencePoints, setReferencePoints] = useState<Vector3[]>([]);
  const [pickingReference, setPickingReference] = useState(false);
  const [selected, setSelected] = useState<string>();
  const [tool, setTool] = useState<"orbit" | "translate" | "rotate">("orbit");
  const [structural, setStructural] = useState(false);
  const [layers, setLayers] = useState<Layers>({
    structure: true,
    entrances: true,
    uncertain: false,
    path: true,
    labels: false,
    cutaway: true,
    observed: false,
    transient: false,
  });
  const [past, setPast] = useState<Scene[]>([]);
  const [future, setFuture] = useState<Scene[]>([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [navigationOpen, setNavigationOpen] = useState(
    () => window.innerWidth > 1000,
  );
  const [inspectorOpen, setInspectorOpen] = useState(
    () => window.innerWidth > 1000,
  );
  const togglePanel = (side: "navigation" | "inspector") => {
    if (side === "navigation") {
      setNavigationOpen((open) => !open);
      if (window.innerWidth <= 1000) setInspectorOpen(false);
    } else {
      setInspectorOpen((open) => !open);
      if (window.innerWidth <= 1000) setNavigationOpen(false);
    }
  };
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 1000px)");
    const resize = () => {
      if (narrow.matches) {
        setNavigationOpen(false);
        setInspectorOpen(false);
      }
    };
    narrow.addEventListener("change", resize);
    return () => narrow.removeEventListener("change", resize);
  }, []);
  const importInput = useRef<HTMLInputElement>(null);
  const importedNotice = useRef<string | undefined>(undefined);
  const scene = scan?.scene;
  const route = useSceneRoute(scan, saving || !active);
  useEffect(() => {
    setReferencePoints([]);
    setPickingReference(false);
  }, [scene, active]);
  const object = scene?.objects.find((o) => o.id === selected && !o.deleted);
  useEffect(() => {
    setSelected(undefined);
    setPast([]);
    setFuture([]);
    setNotice(
      importedNotice.current && importedNotice.current === scan?.id
        ? "Export reloaded and saved as a new scan."
        : "",
    );
    importedNotice.current = undefined;
    setError("");
  }, [scan?.id]);
  const persist = async (
    next: Scene,
    confirmed = false,
    history: "edit" | "undo" | "redo" = "edit",
  ) => {
    if (!scan || !scene || saving) return;
    setSaving(true);
    setError("");
    try {
      const result = await api.save(scan, next, structural, confirmed);
      if (history === "edit") {
        setPast((p) => [...p.slice(-29), scene]);
        setFuture([]);
      }
      if (history === "undo") {
        setPast((p) => p.slice(0, -1));
        setFuture((f) => [...f, scene]);
      }
      if (history === "redo") {
        setFuture((f) => f.slice(0, -1));
        setPast((p) => [...p, scene]);
      }
      onChange(result);
      setNotice("Changes saved.");
    } catch (e) {
      setError((e as Error).message);
      onChange({ ...scan, scene: { ...scene } });
    } finally {
      setSaving(false);
    }
  };
  const applyCalibration = async (calibration: ScaleCalibration | null) => {
    if (!scan || !scene || saving) return;
    setSaving(true);
    setError("");
    try {
      const result = await api.calibrate(scan, calibration);
      setPast((p) => [...p.slice(-29), scene]);
      setFuture([]);
      onChange(result);
      setNotice(
        calibration
          ? "Room scale saved. Dimensions remain estimates."
          : "Scale reference removed; object edits preserved.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const pickReference = (point: Vector3) => {
    if (!pickingReference || saving) return;
    const next = [...referencePoints, point];
    setReferencePoints(next);
    if (next.length === 2) setPickingReference(false);
  };
  const displayReference = referencePoints.length
    ? referencePoints
    : scene?.calibration?.reference_points.map(
        (p) =>
          p.map((v) => v * calibrationFactor(scene.calibration)) as Vector3,
      );
  const changeTransform = (id: string, transform: Transform) => {
    if (!scene) return;
    const current = scene.objects.find((o) => o.id === id);
    if (!current) return;
    const p = [...transform.position] as Vector3;
    if (current.supporting_surface)
      p[1] = Math.max((current.size[1] * transform.scale[1]) / 2, p[1]);
    void persist({
      ...scene,
      objects: scene.objects.map((o) =>
        o.id === id ? { ...o, ...transform, position: p, modified: true } : o,
      ),
    });
  };
  const nudge = (axis: number, amount: number) => {
    if (!object) return;
    const position = [...object.position] as Vector3;
    position[axis] += amount;
    changeTransform(object.id, {
      position,
      rotation: object.rotation,
      scale: object.scale,
    });
  };
  const rotate = (amount: number) => {
    if (!object) return;
    const rotation = [...object.rotation] as Vector3;
    rotation[1] += amount;
    changeTransform(object.id, {
      position: object.position,
      rotation,
      scale: object.scale,
    });
  };
  const remove = () => {
    if (!scene || !object) return;
    const confirmed =
      !object.structural ||
      confirm(
        `Delete structural element “${object.label}”? This may remove an entrance or boundary.`,
      );
    if (confirmed)
      void persist(
        {
          ...scene,
          objects: scene.objects.map((o) =>
            o.id === object.id ? { ...o, deleted: true, modified: true } : o,
          ),
        },
        object.structural,
      );
  };
  const reset = async () => {
    if (!scan || saving) return;
    setSaving(true);
    setError("");
    try {
      const result = await api.reset(scan.id);
      if (scene) setPast((p) => [...p, scene]);
      setFuture([]);
      onChange(result);
      setNotice("Original reconstruction restored.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const exportScene = async () => {
    if (!scan) return;
    try {
      const bundle = await api.export(scan.id);
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(bundle)], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `spatial-scan-${scan.id}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(
        "Exported edited scene, original reconstruction and provenance.",
      );
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const importScene = async (file?: File) => {
    if (!file) return;
    setError("");
    setSaving(true);
    try {
      if (file.size > 80 * 1024 ** 2)
        throw new Error("Scene import exceeds 80 MB.");
      const bundle: unknown = JSON.parse(await file.text());
      const result = await api.import(bundle);
      importedNotice.current = result.id;
      onChange(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
      if (importInput.current) importInput.current.value = "";
    }
  };
  const editable = !!object && (!object.structural || structural) && !saving;
  return (
    <section
      className={`view modeler-view ${active ? "is-active" : ""}`}
      aria-label="3D modeling environment"
      aria-hidden={!active}
      inert={!active}
    >
      <header className="modeler-topbar">
        <button
          className="icon-button back-button"
          onClick={onBack}
          aria-label="Return to dashboard"
        >
          ←
        </button>
        <div className="model-title">
          <span className="status-dot" />
          <div>
            <p>
              {scan
                ? `${scan.status} / ${scan.processing_mode} / estimated meters`
                : "Workspace / awaiting scan"}
            </p>
            <h1>{scan?.name || "Your spatial model"}</h1>
          </div>
        </div>
        <div className="model-actions">
          <button
            onClick={() => importInput.current?.click()}
            disabled={saving}
          >
            Import JSON
          </button>
          <input
            ref={importInput}
            className="visually-hidden"
            type="file"
            accept="application/json,.json"
            aria-label="Import scene file"
            onChange={(e) => void importScene(e.target.files?.[0])}
          />
          <button
            className="primary-action"
            onClick={() => void exportScene()}
            disabled={!scene || saving}
          >
            Export JSON
          </button>
        </div>
      </header>
      <nav className="sandbox-panel-bar" aria-label="Sandbox panels">
        <button
          aria-expanded={navigationOpen}
          aria-controls="navigation-panel"
          onClick={() => togglePanel("navigation")}
        >
          <span aria-hidden="true">☷</span> Agent & Pathfinder
        </button>
        <span className="sandbox-hint">Drag to orbit · Scroll to zoom</span>
        <button
          aria-expanded={inspectorOpen}
          aria-controls="object-panel"
          onClick={() => togglePanel("inspector")}
        >
          Object editor <span aria-hidden="true">☷</span>
        </button>
      </nav>
      <div
        className="editor-layout sandbox-layout"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            if (event.target instanceof HTMLElement) event.target.blur();
            setNavigationOpen(false);
            setInspectorOpen(false);
            route.cancelPick();
            setPickingReference(false);
            document
              .querySelector<HTMLButtonElement>(".sandbox-panel-bar button")
              ?.focus();
          }
        }}
      >
        <aside
          id="navigation-panel"
          className="editor-navigation sandbox-drawer"
          aria-label="Agent and Pathfinder"
          hidden={!navigationOpen}
        >
          <header className="drawer-heading">
            <div>
              <span className="drawer-eyebrow">Plan your next move</span>
              <h2>Agent & Pathfinder</h2>
            </div>
            <button
              className="drawer-close"
              aria-label="Close Agent and Pathfinder"
              onClick={() => setNavigationOpen(false)}
            >
              ←
            </button>
          </header>
          <div className="drawer-content">
            {scene && (
              <RoutePanel
                scene={scene}
                route={route}
                disabled={saving}
                onPick={(which) => {
                  setPickingReference(false);
                  setTool("orbit");
                  route.pick(which);
                  if (window.innerWidth <= 1000) setNavigationOpen(false);
                }}
              />
            )}

            {!scene && (
              <div className="drawer-empty">
                <h3>A model is your starting point</h3>
                <p>
                  Open a completed scan or import a scene to choose destinations
                  and plan a path.
                </p>
              </div>
            )}
            <details className="agent-capabilities">
              <summary>Agent capabilities</summary>
              <p className="input-meta">
                Choose destinations in the model or from the doorway lists.
                Natural-language mission commands are not connected to this
                workspace yet.
              </p>
            </details>
            {scan?.warnings.some((warning) =>
              warning.startsWith("Visual review"),
            ) && (
              <details>
                <summary>Model quality review</summary>
                {scan.warnings
                  .filter(
                    (warning) =>
                      warning.startsWith("Visual review") ||
                      warning.startsWith("Review concern:"),
                  )
                  .map((warning, index) => (
                    <p className="input-meta" key={index}>
                      {warning}
                    </p>
                  ))}
                {scan.source !== "import" && (
                  <a
                    href={`${API_BASE}/scans/${scan.id}/artifacts/gemini-review.json`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View review report
                  </a>
                )}
                <p className="input-meta">
                  Visual review does not verify measurements or safe exit
                  routes.
                </p>
              </details>
            )}
            {
              <details>
                <summary>Live camera (separate from scan)</summary>
                <CameraFeed camera={camera} compact visible={active} />
              </details>
            }
          </div>
        </aside>
        <div className="editor-canvas">
          <SceneViewer
            scene={scene}
            active={active}
            mode="modeler"
            selected={selected}
            onSelect={setSelected}
            onTransform={changeTransform}
            tool={saving || pickingReference || route.picking ? "orbit" : tool}
            pickingRoute={!!route.picking && !saving}
            onRoutePoint={route.pickPoint}
            routePolyline={route.result?.polyline}
            routePoints={[
              route.result?.start.point ?? route.start?.point,
              route.result?.end.point ?? route.end?.point,
            ]}
            pickingReference={pickingReference && !saving}
            referencePoints={displayReference}
            onReferencePoint={pickReference}
            structural={structural}
            layers={layers}
          />
          <p
            role={error ? "alert" : "status"}
            className={`sandbox-notice ${error ? "editor-error" : "input-meta"}`}
          >
            {error || (saving ? "Saving edits…" : notice)}
          </p>
        </div>
        <aside
          id="object-panel"
          className="editor-inspector sandbox-drawer"
          aria-label="Scene editor"
          hidden={!inspectorOpen}
        >
          <header className="drawer-heading">
            <div>
              <span className="drawer-eyebrow">Refine your model</span>
              <h2>Object editor</h2>
            </div>
            <button
              className="drawer-close"
              aria-label="Close object editor"
              onClick={() => setInspectorOpen(false)}
            >
              →
            </button>
          </header>
          <div className="drawer-content">
            <label>
              Scene element
              <select
                value={selected || ""}
                onChange={(e) => setSelected(e.target.value || undefined)}
              >
                <option value="">Select an object</option>
                {scene?.objects
                  .filter((o) => !o.deleted)
                  .map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                      {o.entrance ? " · opening candidate" : ""}
                    </option>
                  ))}
              </select>
            </label>
            <div
              className="editor-toolbar"
              role="toolbar"
              aria-label="Model tools"
            >
              {(["orbit", "translate", "rotate"] as const).map((t) => (
                <button
                  key={t}
                  aria-pressed={tool === t}
                  onClick={() => setTool(t)}
                  disabled={t !== "orbit" && !editable}
                >
                  {t === "translate"
                    ? "Move"
                    : t === "rotate"
                      ? "Rotate"
                      : "Orbit"}
                </button>
              ))}
              <button
                onClick={() => setSelected(undefined)}
                disabled={!selected}
              >
                Deselect
              </button>
            </div>
            <div className="editor-toolbar">
              <button
                disabled={!past.length || saving}
                onClick={() =>
                  void persist(past[past.length - 1], true, "undo")
                }
              >
                Undo
              </button>
              <button
                disabled={!future.length || saving}
                onClick={() =>
                  void persist(future[future.length - 1], true, "redo")
                }
              >
                Redo
              </button>
              <button disabled={!scene || saving} onClick={() => void reset()}>
                Reset scene
              </button>
            </div>
            {object ? (
              <>
                <fieldset disabled={!editable}>
                  <legend>Transform</legend>
                  <div className="transform-fields">
                    {(["position", "rotation"] as const).map((field) => (
                      <div key={field}>
                        <span>
                          {field === "rotation"
                            ? "Rotation (degrees)"
                            : "Position (estimated m)"}
                        </span>
                        {(["X", "Y", "Z"] as const).map((axis, i) => (
                          <label key={axis}>
                            {axis}
                            <input
                              key={`${object.id}-${object[field][i]}`}
                              type="number"
                              step={field === "rotation" ? 5 : 0.1}
                              aria-label={`${field} ${axis}`}
                              defaultValue={(
                                object[field][i] *
                                (field === "rotation" ? 180 / Math.PI : 1)
                              ).toFixed(2)}
                              onBlur={(e) => {
                                const v = Number(e.target.value);
                                if (!Number.isFinite(v)) return;
                                const values = [...object[field]] as Vector3;
                                values[i] =
                                  v *
                                  (field === "rotation" ? Math.PI / 180 : 1);
                                if (
                                  Math.abs(values[i] - object[field][i]) <
                                  0.0001
                                )
                                  return;
                                changeTransform(object.id, {
                                  position: object.position,
                                  rotation: object.rotation,
                                  scale: object.scale,
                                  [field]: values,
                                });
                              }}
                            />
                          </label>
                        ))}
                      </div>
                    ))}
                  </div>
                  <div className="editor-toolbar">
                    <button onClick={() => nudge(0, -0.1)}>Move left</button>
                    <button onClick={() => nudge(0, 0.1)}>Move right</button>
                    <button onClick={() => rotate(Math.PI / 12)}>
                      Rotate 15°
                    </button>
                    <button onClick={remove}>Delete object</button>
                  </div>
                </fieldset>
                <ObjectDetails object={object} />
                {object.structural && !structural && (
                  <p className="input-meta">
                    Protected structure. Enable structural editing to move or
                    delete.
                  </p>
                )}
                <details>
                  <summary>
                    Source-frame evidence ({object.source_frames.length})
                  </summary>
                  {scan?.source === "import" ? (
                    <p>
                      Source frame references are preserved; images remain with
                      the original scan.
                    </p>
                  ) : (
                    object.source_frames.slice(0, 6).map((frame) => (
                      <a
                        key={frame}
                        href={`${API_BASE}/scans/${scan?.id}/artifacts/frame-${String(frame).padStart(6, "0")}.jpg`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <img
                          className="evidence-image"
                          alt={`Source frame ${frame}`}
                          src={`${API_BASE}/scans/${scan?.id}/artifacts/${scan?.processing_mode === "blender" ? "frame" : "segmentation"}-${String(frame).padStart(6, "0")}.jpg`}
                        />
                      </a>
                    ))
                  )}
                </details>
              </>
            ) : (
              <p className="input-meta">
                Click observed geometry or choose an element. Drag to orbit,
                right-drag to pan, scroll to zoom. Move and Rotate show a
                transform gizmo.
              </p>
            )}
            <details>
              <summary>Visible layers</summary>
              <div className="layer-controls">
                {(
                  [
                    ["labels", "Semantic labels"],
                    ["structure", "Structural geometry"],
                    ["entrances", "Entrances / exits"],
                    ["uncertain", "Low-confidence geometry"],
                    ["transient", "Moving candidates"],
                    ["path", "Camera path"],
                    ["cutaway", "Cutaway walls / ceiling"],
                    ["observed", "Observed surfaces"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={layers[key]}
                      onChange={(e) =>
                        setLayers({ ...layers, [key]: e.target.checked })
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            </details>
            {scene && (
              <ScalePanel
                key={scan?.id}
                scene={scene}
                points={referencePoints}
                picking={pickingReference}
                busy={saving}
                onPick={() => {
                  route.cancelPick();
                  setReferencePoints([]);
                  setPickingReference(true);
                  if (window.innerWidth <= 1000) setInspectorOpen(false);
                  setTool("orbit");
                }}
                onCancel={() => {
                  setReferencePoints([]);
                  setPickingReference(false);
                }}
                onApply={(reference) => void applyCalibration(reference)}
              />
            )}
            <label className="structural-mode">
              <input
                type="checkbox"
                checked={structural}
                onChange={(e) => setStructural(e.target.checked)}
              />
              Enable structural editing
            </label>
          </div>
        </aside>
      </div>
    </section>
  );
}
function ObjectDetails({ object: o }: { object: SceneObject }) {
  return (
    <div className="object-details" aria-label="Selected object details">
      <h2>{o.label}</h2>
      <dl>
        {[
          ["Class", o.kind],
          ["Confidence", `${Math.round(o.confidence * 100)}%`],
          ["Position", o.position.map((v) => v.toFixed(2)).join(", ")],
          [
            "Rotation",
            o.rotation.map((v) => ((v * 180) / Math.PI).toFixed(1)).join(", ") +
              "°",
          ],
          [
            "Dimensions",
            o.size.map((v, i) => (v * o.scale[i]).toFixed(2)).join(" × ") +
              " m (estimated)",
          ],
          ["Type", o.structural ? "Structural / protected" : "Movable"],
          ["Geometry", o.provenance.replaceAll("_", " ")],
          [
            "Motion",
            o.transient
              ? "Moving candidate (separate layer)"
              : "No motion flag",
          ],
          ["Edited", o.modified ? "Yes" : "No"],
          ["Supporting surface", o.supporting_surface || "Unverified"],
          ["Method", o.method],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {o.entrance && (
        <p className="opening-note">
          Opening candidate · exit function unverified
        </p>
      )}
    </div>
  );
}
