import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import type { Layers, Scene, SceneObject, Transform, Vector3 } from "../types";
interface Props {
  scene?: Scene | null;
  active: boolean;
  mode: "preview" | "modeler";
  onOpen?(): void;
  selected?: string;
  onSelect?(id?: string): void;
  onTransform?(id: string, transform: Transform): void;
  tool?: "orbit" | "translate" | "rotate";
  structural?: boolean;
  pickingReference?: boolean;
  referencePoints?: Vector3[];
  onReferencePoint?(point: Vector3): void;
  layers?: Layers;
}
const defaultLayers: Layers = {
  structure: true,
  entrances: true,
  uncertain: false,
  path: true,
  labels: false,
  cutaway: true,
  observed: false,
  transient: false,
};
export function SceneViewer(props: Props) {
  const { scene, active, mode } = props;
  const host = useRef<HTMLDivElement>(null);
  const latest = useRef(props);
  latest.current = props;
  const [error, setError] = useState(false);
  const [hover, setHover] = useState("");
  const [fps, setFps] = useState(0);
  const actions = useRef<{
    reset(): void;
    zoom(factor: number): void;
    sync(): void;
  } | null>(null);
  useEffect(() => {
    actions.current?.sync();
  }, [
    props.selected,
    props.tool,
    props.layers,
    props.structural,
    props.pickingReference,
    props.referencePoints,
  ]);
  useEffect(() => {
    const container = host.current;
    if (!container || !active || !scene) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        preserveDrawingBuffer: true,
      });
    } catch {
      setError(true);
      return;
    }
    setError(false);
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
    renderer.setClearColor(0x080d10);
    renderer.localClippingEnabled = true;
    renderer.domElement.setAttribute("aria-label", "Interactive 3D scan model");
    renderer.domElement.dataset.objects = String(
      scene.objects.filter((o) => !o.deleted).length,
    );
    container.prepend(renderer.domElement);
    const world = new THREE.Scene();
    world.add(new THREE.HemisphereLight(0xffffff, 0x667788, 2.2));
    const camera = new THREE.PerspectiveCamera(48, 1, 0.02, 200);
    const orbit = new OrbitControls(camera, renderer.domElement);
    orbit.enableDamping = true;
    orbit.minDistance = 0.2;
    orbit.maxDistance = 80;
    orbit.enablePan = true;
    const transform = new TransformControls(camera, renderer.domElement);
    world.add(transform.getHelper());
    transform.addEventListener("dragging-changed", (event) => {
      orbit.enabled = !event.value;
    });
    const groups = new Map<string, THREE.Group>();
    const labels = new Map<string, THREE.Sprite>();
    const pickable: THREE.Object3D[] = [];
    const path = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(
        scene.camera_path.map((p) => new THREE.Vector3(...p)),
      ),
      new THREE.LineBasicMaterial({ color: 0x00e5ff }),
    );
    world.add(path);
    const makeLabel = (object: SceneObject) => {
      const canvas = document.createElement("canvas");
      canvas.width = 512;
      canvas.height = 64;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = "#061016dc";
      ctx.fillRect(0, 0, 512, 64);
      ctx.font = "24px sans-serif";
      ctx.fillStyle = object.entrance ? "#ffbf69" : "#ffffff";
      ctx.fillText(object.label, 12, 40);
      const texture = new THREE.CanvasTexture(canvas);
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: texture, depthTest: false }),
      );
      sprite.scale.set(1.8, 0.225, 1);
      sprite.position.y = object.size[1] / 2 + 0.2;
      return sprite;
    };
    for (const object of scene.objects) {
      if (object.deleted) continue;
      const group = new THREE.Group();
      group.userData.id = object.id;
      group.position.set(...object.position);
      group.rotation.set(...object.rotation);
      group.scale.set(...object.scale);
      if (object.entrance && !object.observed_geometry) {
        const [w, h, d] = object.size;
        const verticalZ = d > w;
        const span = Math.max(w, d);
        const geometry = new THREE.BoxGeometry(0.045, 1, 0.045);
        const material = new THREE.MeshBasicMaterial({ color: 0xffb454 });
        for (const side of [-1, 1]) {
          const post = new THREE.Mesh(geometry, material);
          post.scale.y = h;
          if (verticalZ) post.position.z = (side * span) / 2;
          else post.position.x = (side * span) / 2;
          group.add(post);
        }
        const top = new THREE.Mesh(
          new THREE.BoxGeometry(
            verticalZ ? 0.045 : span,
            0.045,
            verticalZ ? span : 0.045,
          ),
          material,
        );
        top.position.y = h / 2;
        group.add(top);
      } else {
        const objectGeometry =
          (latest.current.layers?.observed && object.observed_geometry) ||
          object.geometry;
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(objectGeometry.vertices.flat(), 3),
        );
        geometry.setAttribute(
          "color",
          new THREE.Float32BufferAttribute(objectGeometry.colors.flat(), 3),
        );
        if (objectGeometry.triangles.length) {
          geometry.setIndex(objectGeometry.triangles.flat());
          geometry.computeVertexNormals();
          group.add(
            new THREE.Mesh(
              geometry,
              new THREE.MeshStandardMaterial({
                vertexColors: true,
                // Observed room surfaces have no reconstructed back/thickness.
                // Keep their existing triangles visible from either viewing side.
                side: THREE.DoubleSide,
                emissive: object.entrance ? 0x553000 : 0x000000,
                roughness: 0.95,
                metalness: 0,
              }),
            ),
          );
        } else
          group.add(
            new THREE.Points(
              geometry,
              new THREE.PointsMaterial({
                vertexColors: true,
                size: 0.035,
                sizeAttenuation: true,
              }),
            ),
          );
      }
      const label = makeLabel(object);
      group.add(label);
      labels.set(object.id, label);
      world.add(group);
      groups.set(object.id, group);
      pickable.push(group);
    }
    const bounds = new THREE.Box3();
    for (const group of groups.values()) bounds.expandByObject(group);
    if (bounds.isEmpty())
      bounds.setFromCenterAndSize(
        new THREE.Vector3(),
        new THREE.Vector3(4, 4, 4),
      );
    const center = bounds.getCenter(new THREE.Vector3());
    const span = Math.max(3, bounds.getSize(new THREE.Vector3()).length());
    const reset = () => {
      camera.position
        .copy(center)
        .add(new THREE.Vector3(0.6, 0.48, 0.8).multiplyScalar(span));
      orbit.target.copy(center);
      orbit.update();
    };
    reset();
    const hoverBox = new THREE.BoxHelper(new THREE.Object3D(), 0x79dbea),
      selectBox = new THREE.BoxHelper(new THREE.Object3D(), 0xffffff);
    hoverBox.visible = selectBox.visible = false;
    world.add(hoverBox, selectBox);
    let hovered: string | undefined;
    const cutawayPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1.3);
    const wallIds = new Set(
      scene.objects
        .filter((object) => object.kind === "wall" && !object.deleted)
        .map((object) => object.id),
    );
    const reference = new THREE.Group();
    world.add(reference);
    const sync = () => {
      for (const child of [...reference.children]) {
        const mesh = child as THREE.Mesh;
        mesh.geometry?.dispose();
        (mesh.material as THREE.Material)?.dispose();
        reference.remove(child);
      }
      const points = latest.current.referencePoints || [];
      renderer.domElement.dataset.referencePoints = String(points.length);
      if (points.length) {
        for (const point of points) {
          const marker = new THREE.Mesh(
            new THREE.SphereGeometry(0.035, 12, 8),
            new THREE.MeshBasicMaterial({ color: 0xffca70, depthTest: false }),
          );
          marker.position.set(...point);
          marker.renderOrder = 10;
          reference.add(marker);
        }
        if (points.length === 2) {
          const line = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(
              points.map((p) => new THREE.Vector3(...p)),
            ),
            new THREE.LineBasicMaterial({ color: 0xffca70, depthTest: false }),
          );
          line.renderOrder = 10;
          reference.add(line);
        }
      }
      const current = latest.current,
        layers = current.layers || defaultLayers;
      // Layer changes must not leave a highlight on newly hidden geometry.
      hovered = undefined;
      hoverBox.visible = false;
      setHover("");
      renderer.domElement.dataset.hovered = "";
      renderer.domElement.style.cursor = "grab";
      for (const object of scene.objects) {
        const group = groups.get(object.id);
        if (!group) continue;
        group.visible =
          (!object.transient || layers.transient) &&
          (!object.structural || layers.structure) &&
          (!object.entrance || layers.entrances) &&
          ((object.transient && layers.transient) ||
            (object.confidence >= 0.55 && object.kind !== "unknown") ||
            layers.uncertain);
        const mounted =
          !object.modified &&
          object.relationships.some(
            (relationship) =>
              relationship.startsWith("boundary:") &&
              wallIds.has(relationship.slice(9)),
          );
        const clipped =
          layers.cutaway &&
          !object.entrance &&
          (object.kind === "wall" || object.kind === "ceiling" || mounted);
        const geometryBounds = new THREE.Box3();
        group.updateWorldMatrix(true, true);
        group.traverse((child) => {
          if (child instanceof THREE.Mesh || child instanceof THREE.Points) {
            const materials = Array.isArray(child.material)
              ? child.material
              : [child.material];
            for (const material of materials)
              material.clippingPlanes = clipped ? [cutawayPlane] : [];
            if (!child.geometry.boundingBox)
              child.geometry.computeBoundingBox();
            if (child.geometry.boundingBox) {
              geometryBounds.union(
                child.geometry.boundingBox
                  .clone()
                  .applyMatrix4(child.matrixWorld),
              );
            }
          }
        });
        // Fully removed surfaces should not retain labels, selection boxes or handles.
        if (clipped && !geometryBounds.isEmpty() && geometryBounds.min.y > 1.3)
          group.visible = false;
        const label = labels.get(object.id)!;
        label.visible =
          layers.labels &&
          (!clipped || label.getWorldPosition(new THREE.Vector3()).y <= 1.3);
      }
      path.visible = layers.path;
      const selected = current.selected
        ? groups.get(current.selected)
        : undefined;
      selectBox.visible = !!selected && selected.visible;
      if (selected) selectBox.setFromObject(selected);
      transform.detach();
      const object = scene.objects.find((o) => o.id === current.selected);
      if (
        selected?.visible &&
        object?.editable &&
        (!object.structural || current.structural) &&
        current.tool &&
        current.tool !== "orbit"
      ) {
        transform.attach(selected);
        transform.setMode(current.tool);
      }
    };
    actions.current = {
      reset,
      zoom: (factor) => {
        camera.position
          .sub(orbit.target)
          .multiplyScalar(factor)
          .add(orbit.target);
        orbit.update();
      },
      sync,
    };
    sync();
    transform.addEventListener("objectChange", () => {
      if (transform.object) selectBox.setFromObject(transform.object);
    });
    transform.addEventListener("mouseUp", () => {
      const group = transform.object;
      if (!group) return;
      latest.current.onTransform?.(group.userData.id, {
        position: group.position.toArray(),
        rotation: [group.rotation.x, group.rotation.y, group.rotation.z],
        scale: group.scale.toArray(),
      });
    });
    const raycaster = new THREE.Raycaster();
    raycaster.params.Points = { threshold: 0.08 };
    const pointer = new THREE.Vector2();
    let start = { x: 0, y: 0 };
    const hit = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        (-(event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster
        .intersectObjects(
          pickable.filter((g) => g.visible),
          true,
        )
        .filter((hit) => {
          const object = hit.object;
          if (!(object instanceof THREE.Mesh || object instanceof THREE.Points))
            return false;
          const material = Array.isArray(object.material)
            ? object.material[hit.face?.materialIndex ?? 0]
            : object.material;
          const planes = material.clippingPlanes;
          if (!planes?.length) return true;
          // Three.js raycasting ignores material clipping. Use the same world-space
          // half-spaces as rendering so invisible wall faces cannot steal a click.
          const kept = (plane: THREE.Plane) =>
            plane.distanceToPoint(hit.point) >= 0;
          return material.clipIntersection
            ? planes.some(kept)
            : planes.every(kept);
        });
      let object: THREE.Object3D | undefined = hits[0]?.object;
      while (object && !object.userData.id) object = object.parent || undefined;
      return object && hits[0]
        ? {
            id: object.userData.id as string,
            point: hits[0].point.toArray() as Vector3,
          }
        : undefined;
    };
    const move = (event: PointerEvent) => {
      if (transform.dragging) return;
      const id = hit(event)?.id;
      if (id === hovered) return;
      hovered = id;
      setHover(scene.objects.find((o) => o.id === id)?.label || "");
      hoverBox.visible = !!id && id !== latest.current.selected;
      if (id) hoverBox.setFromObject(groups.get(id)!);
      renderer.domElement.style.cursor = latest.current.pickingReference
        ? "crosshair"
        : id
          ? "pointer"
          : "grab";
      renderer.domElement.dataset.hovered = id || "";
    };
    const down = (event: PointerEvent) => {
      start = { x: event.clientX, y: event.clientY };
    };
    const up = (event: PointerEvent) => {
      if (
        event.button !== 0 ||
        Math.hypot(start.x - event.clientX, start.y - event.clientY) > 5 ||
        transform.dragging ||
        transform.axis
      )
        return;
      if (mode === "preview") latest.current.onOpen?.();
      else if (latest.current.pickingReference) {
        const intersection = hit(event);
        if (intersection) latest.current.onReferencePoint?.(intersection.point);
      } else latest.current.onSelect?.(hit(event)?.id);
    };
    const leave = () => {
      hovered = undefined;
      hoverBox.visible = false;
      setHover("");
      renderer.domElement.dataset.hovered = "";
    };
    renderer.domElement.addEventListener("pointermove", move);
    renderer.domElement.addEventListener("pointerdown", down);
    renderer.domElement.addEventListener("pointerup", up);
    renderer.domElement.addEventListener("pointerleave", leave);
    const lost = (e: Event) => {
      e.preventDefault();
      setError(true);
    };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    const resize = () => {
      const { width, height } = container.getBoundingClientRect();
      renderer.setSize(Math.max(1, width), Math.max(1, height));
      camera.aspect = width / Math.max(1, height);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();
    let frames = 0;
    let last = performance.now();
    renderer.setAnimationLoop(() => {
      orbit.update();
      renderer.render(world, camera);
      frames++;
      renderer.domElement.dataset.rendered = String(performance.now());
      const now = performance.now();
      if (now - last > 1000) {
        const value = Math.round((frames * 1000) / (now - last));
        setFps(value);
        renderer.domElement.dataset.fps = String(value);
        frames = 0;
        last = now;
      }
    });
    return () => {
      observer.disconnect();
      renderer.setAnimationLoop(null);
      orbit.dispose();
      transform.dispose();
      world.traverse((object) => {
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose();
        if (mesh.material) {
          for (const material of Array.isArray(mesh.material)
            ? mesh.material
            : [mesh.material]) {
            (material as THREE.MeshBasicMaterial).map?.dispose();
            material.dispose();
          }
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
      actions.current = null;
    };
  }, [scene, active, mode, props.layers?.observed]);
  return (
    <div
      ref={host}
      className={`scene-host ${mode}`}
      data-testid={`scene-${mode}`}
    >
      {(!scene || error) && (
        <div className="scene-empty">
          <span className="empty-cube">◇</span>
          <strong>
            {error ? "3D display unavailable" : "Your space, reconstructed"}
          </strong>
          <p>
            {error
              ? "Enable WebGL to view geometry. Object details, editing fields, and JSON export remain available."
              : "Upload a room video to reconstruct the observed space."}
          </p>
        </div>
      )}
      {scene && !error && (
        <span className="viewer-status">
          {hover || "Observed surfaces · empty space is unknown"} · {fps} FPS
        </span>
      )}
      {mode === "modeler" && (
        <div className="view-controls" aria-label="View controls">
          <button
            onClick={() => actions.current?.zoom(1.15)}
            disabled={!scene || error}
            aria-label="Zoom out"
          >
            −
          </button>
          <button
            onClick={() => actions.current?.reset()}
            disabled={!scene || error}
          >
            Reset view
          </button>
          <button
            onClick={() => actions.current?.zoom(0.85)}
            disabled={!scene || error}
            aria-label="Zoom in"
          >
            +
          </button>
        </div>
      )}
    </div>
  );
}
