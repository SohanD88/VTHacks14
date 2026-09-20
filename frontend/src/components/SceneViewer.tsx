import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import type { Layers, Scene, SceneObject, Transform, Vector3 } from "../types";
interface Props {
  scene?: Scene | null;
  active: boolean;
  mode: "preview" | "modeler";
  onOpen?(): void;
  emptyMessage?: string;
  selected?: string;
  onSelect?(id?: string): void;
  onTransform?(id: string, transform: Transform): void;
  tool?: "orbit" | "translate" | "rotate";
  structural?: boolean;
  pickingReference?: boolean;
  referencePoints?: Vector3[];
  onReferencePoint?(point: Vector3): void;
  pickingRoute?: boolean;
  onRoutePoint?(point: Vector3, objectId: string): void;
  routePolyline?: Vector3[];
  routePoints?: (Vector3 | undefined)[];
  layers?: Layers;
}
function isOpening(object: SceneObject) {
  return (
    object.entrance ||
    ["door", "doorway", "entrance", "exit"].includes(object.kind)
  );
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
function disposeTree(root: THREE.Object3D) {
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    mesh.geometry?.dispose();
    if (mesh.material) {
      for (const material of Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material]) {
        for (const value of Object.values(material))
          if (value instanceof THREE.Texture) value.dispose();
        material.dispose();
      }
    }
  });
}
export function SceneViewer(props: Props) {
  const { scene, active, mode } = props;
  const host = useRef<HTMLDivElement>(null);
  const latest = useRef(props);
  latest.current = props;
  const [error, setError] = useState(false);
  const [model, setModel] = useState<{ hash: string; root: THREE.Group }>();
  const asset = scene?.asset;
  useEffect(() => {
    let cancelled = false;
    let loaded: THREE.Group | undefined;
    if (!asset) {
      setModel(undefined);
      return;
    }
    setError(false);
    const bytes = Uint8Array.from(atob(asset.data), (c) => c.charCodeAt(0));
    void new GLTFLoader()
      .parseAsync(bytes.buffer, "")
      .then((gltf) => {
        loaded = gltf.scene;
        if (!cancelled) setModel({ hash: asset.sha256, root: gltf.scene });
        else disposeTree(gltf.scene);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
      if (loaded) disposeTree(loaded);
    };
  }, [asset?.sha256, asset?.data]);
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
    props.pickingRoute,
    props.routePolyline,
    props.routePoints,
  ]);
  useEffect(() => {
    const container = host.current;
    if (
      !container ||
      !active ||
      !scene ||
      (scene.asset && model?.hash !== scene.asset.sha256)
    )
      return;
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
    let environment: THREE.WebGLRenderTarget | undefined;
    if (scene.asset) {
      const generator = new THREE.PMREMGenerator(renderer);
      const room = new RoomEnvironment();
      environment = generator.fromScene(room, 0.04);
      world.environment = environment.texture;
      world.environmentIntensity = 0.8;
      room.dispose();
      generator.dispose();
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.1;
    }
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
    const openings = new Map<string, THREE.Box3Helper>();
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
      ctx.fillStyle = isOpening(object) ? "#ffbf69" : "#ffffff";
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
      if (object.asset_node && model) {
        let template: THREE.Object3D | undefined;
        model.root.traverse((node) => {
          if (node.userData.spatial_id === object.asset_node) template = node;
        });
        if (!template) {
          setError(true);
          continue;
        }
        const imported = template.clone(true);
        // Exported root placement is already represented by the scene transform.
        imported.position.set(0, 0, 0);
        imported.quaternion.identity();
        imported.scale.set(1, 1, 1);
        imported.traverse((node) => {
          if (node instanceof THREE.Mesh) {
            node.geometry = node.geometry.clone();
            const cloneMaterial = (material: THREE.Material) => {
              const copy = material.clone();
              for (const key of Object.keys(copy)) {
                const value = (copy as unknown as Record<string, unknown>)[key];
                if (value instanceof THREE.Texture)
                  (copy as unknown as Record<string, unknown>)[key] =
                    value.clone();
              }
              return copy;
            };
            node.material = Array.isArray(node.material)
              ? node.material.map(cloneMaterial)
              : cloneMaterial(node.material);
          }
        });
        group.add(imported);
      } else if (object.entrance && !object.observed_geometry) {
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
                emissive: 0x000000,
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
      if (isOpening(object)) {
        // Local bounds keep the outline aligned while moving, rotating or scaling a door.
        const localBounds = new THREE.Box3();
        group.updateMatrixWorld(true);
        const inverse = group.matrixWorld.clone().invert();
        group.traverse((node) => {
          if (!(node instanceof THREE.Mesh || node instanceof THREE.Points))
            return;
          node.geometry.computeBoundingBox();
          if (node.geometry.boundingBox)
            localBounds.union(
              node.geometry.boundingBox
                .clone()
                .applyMatrix4(
                  new THREE.Matrix4().multiplyMatrices(
                    inverse,
                    node.matrixWorld,
                  ),
                ),
            );
        });
        if (!localBounds.isEmpty()) {
          const outline = new THREE.Box3Helper(localBounds, 0xffb454);
          (outline.material as THREE.LineBasicMaterial).depthTest = false;
          (outline.material as THREE.LineBasicMaterial).depthWrite = false;
          outline.renderOrder = 5;
          group.add(outline);
          openings.set(object.id, outline);
        }
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
        .add(
          (scene.asset
            ? scene.preview_direction
              ? new THREE.Vector3(...scene.preview_direction).normalize()
              : new THREE.Vector3(0.12, 0.52, 0.86)
            : new THREE.Vector3(0.6, 0.48, 0.8)
          ).multiplyScalar(span),
        );
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
    const routeOverlay = new THREE.Group();
    world.add(routeOverlay);
    const sync = () => {
      disposeTree(routeOverlay);
      routeOverlay.clear();
      const routePoints = latest.current.routePolyline || [];
      renderer.domElement.dataset.routePoints = String(routePoints.length);
      renderer.domElement.dataset.routeMarkers = String(
        latest.current.routePoints?.filter(Boolean).length ?? 0,
      );
      if (routePoints.length > 1) {
        const curve = new THREE.CurvePath<THREE.Vector3>();
        for (let i = 1; i < routePoints.length; i++) {
          curve.add(
            new THREE.LineCurve3(
              new THREE.Vector3(...routePoints[i - 1]),
              new THREE.Vector3(...routePoints[i]),
            ),
          );
        }
        const routeMesh = new THREE.Mesh(
          new THREE.TubeGeometry(
            curve,
            Math.min(20000, Math.max(32, routePoints.length * 8)),
            0.022,
            6,
            false,
          ),
          new THREE.MeshBasicMaterial({
            color: 0x74ff9a,
            depthWrite: false,
          }),
        );
        routeMesh.renderOrder = 12;
        routeOverlay.add(routeMesh);
      }
      latest.current.routePoints?.forEach((point, i) => {
        if (!point) return;
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(0.065, 16, 10),
          new THREE.MeshBasicMaterial({
            color: i === 0 ? 0x74ff9a : 0xffb454,
            depthTest: false,
            depthWrite: false,
          }),
        );
        marker.position.set(...point);
        marker.renderOrder = 13;
        routeOverlay.add(marker);
      });
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
      renderer.domElement.style.cursor =
        latest.current.pickingReference || latest.current.pickingRoute
          ? "crosshair"
          : "grab";
      for (const object of scene.objects) {
        const group = groups.get(object.id);
        if (!group) continue;
        group.visible =
          !(scene.asset && layers.cutaway && object.cutaway_hidden) &&
          (!object.transient || layers.transient) &&
          (!object.structural || layers.structure) &&
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
          !scene.asset &&
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
        const outline = openings.get(object.id);
        if (outline) outline.visible = layers.entrances;
        label.visible =
          (layers.labels || (isOpening(object) && layers.entrances)) &&
          (!clipped || label.getWorldPosition(new THREE.Vector3()).y <= 1.3);
      }
      renderer.domElement.dataset.highlightedOpenings = String(
        [...openings].filter(
          ([id, outline]) => outline.visible && groups.get(id)?.visible,
        ).length,
      );
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
      renderer.domElement.style.cursor =
        latest.current.pickingReference || latest.current.pickingRoute
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
      else if (latest.current.pickingRoute) {
        const intersection = hit(event);
        if (intersection)
          latest.current.onRoutePoint?.(intersection.point, intersection.id);
      } else if (latest.current.pickingReference) {
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
      disposeTree(world);
      environment?.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      actions.current = null;
    };
  }, [scene, active, mode, props.layers?.observed, model]);
  return (
    <div
      ref={host}
      className={`scene-host ${mode}`}
      data-testid={`scene-${mode}`}
    >
      {(!scene ||
        error ||
        (scene.asset && model?.hash !== scene.asset.sha256)) && (
        <div className="scene-empty">
          <span className="empty-cube">◇</span>
          <strong>
            {error
              ? "3D display unavailable"
              : scene?.asset
                ? "Loading Blender model…"
                : "Your space, reconstructed"}
          </strong>
          <p>
            {error
              ? "Enable WebGL to view geometry. Object details, editing fields, and JSON export remain available."
              : props.emptyMessage ||
                "Upload a room video to reconstruct the observed space."}
          </p>
        </div>
      )}
      {scene && !error && (
        <span className="viewer-status">
          {hover ||
            (scene.asset
              ? "Blender model · estimated geometry"
              : "Observed surfaces · empty space is unknown")}{" "}
          · {fps} FPS
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
