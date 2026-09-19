import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { Scene, Vector3 } from '../types';

interface Props { scene?: Scene; active: boolean; mode: 'preview' | 'modeler'; onOpen?: () => void }

export function SceneViewer({ scene, active, mode, onOpen }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const pointerStart = useRef<{ x: number; y: number } | null>(null);
  const [error, setError] = useState(false);
  const actions = useRef<{ reset(): void; zoom(factor: number): void } | null>(null);

  useEffect(() => {
    const container = host.current;
    if (!container || !active || !scene) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    catch { setError(true); return; }
    setError(false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.setAttribute('aria-label', 'Interactive 3D scan model');
    renderer.domElement.dataset.objects = String(scene.objects.length);
    container.prepend(renderer.domElement);
    const world = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, .1, 100);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.minDistance = 5;
    controls.maxDistance = 30;
    controls.maxPolarAngle = Math.PI * .49;
    controls.enablePan = mode === 'modeler';
    controls.autoRotate = mode === 'preview' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    controls.autoRotateSpeed = .35;
    const reset = () => { camera.position.set(10, 10, 12).multiplyScalar(Math.min(1.6, Math.max(1, .9 / camera.aspect))); controls.target.set(0, .5, 0); controls.update(); };
    reset();
    actions.current = { reset, zoom: (factor) => {
      const offset = camera.position.clone().sub(controls.target);
      offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, 5, 30));
      camera.position.copy(controls.target).add(offset); controls.update();
    } };
    const grid = new THREE.GridHelper(16, 16, 0x25424a, 0x102025);
    grid.position.y = -.02;
    world.add(grid);
    const addBox = (position: Vector3, size: Vector3, color = 0x00d7f5, opacity = .1) => {
      const geometry = new THREE.BoxGeometry(...size);
      const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
      mesh.position.set(...position);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ color, transparent: true, opacity: .65 }));
      mesh.add(edges);
      world.add(mesh);
    };
    scene.rooms.forEach(room => {
      const [x, y, z] = room.center, [w, h, d] = room.size;
      addBox([x, y - h / 2, z], [w, .04, d], 0x00d7f5, .035);
      addBox([x, y, z - d / 2], [w, h, .04], 0x00d7f5, .035);
      addBox([x - w / 2, y, z], [.04, h, d], 0x00d7f5, .035);
    });
    scene.objects.forEach(object => addBox(object.position, object.size, object.kind === 'person' ? 0xffffff : 0x00d7f5));
    const points = scene.camera_path.map(point => new THREE.Vector3(...point));
    const path = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color: 0xffffff }));
    world.add(path);
    let framed = false;
    const resize = () => {
      const { width, height } = container.getBoundingClientRect();
      renderer.setSize(Math.max(1, width), Math.max(1, height));
      camera.aspect = width / Math.max(1, height);
      camera.updateProjectionMatrix();
      if (!framed) { reset(); framed = true; }
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();
    renderer.setAnimationLoop(() => { controls.update(); renderer.render(world, camera); });
    return () => {
      observer.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      world.traverse(object => {
        const renderable = object as THREE.Mesh;
        renderable.geometry?.dispose();
        if (renderable.material) {
          const materials = Array.isArray(renderable.material) ? renderable.material : [renderable.material];
          materials.forEach(material => material.dispose());
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
      actions.current = null;
    };
  }, [scene, active, mode]);

  return <div ref={host} className={`scene-host ${mode}`} data-testid={`scene-${mode}`}
    onPointerDown={event => { pointerStart.current = { x: event.clientX, y: event.clientY }; }}
    onPointerCancel={() => { pointerStart.current = null; }}
    onPointerUp={event => {
      const start = pointerStart.current;
      pointerStart.current = null;
      if (mode === 'preview' && event.button === 0 && start && Math.hypot(event.clientX - start.x, event.clientY - start.y) < 5) onOpen?.();
    }}>
    {(!scene || error) && <div className="scene-empty"><span className="empty-cube">◇</span><strong>{error ? '3D display unavailable' : 'Your space, reconstructed'}</strong><p>{error ? 'Enable WebGL to view the model. Scan results and JSON export remain available.' : 'Run a demo scan to bring a scene into this workspace.'}</p></div>}
    {mode === 'modeler' && <div className="view-controls" aria-label="View controls">
      <button onClick={() => actions.current?.zoom(1.15)} disabled={!scene || error} aria-label="Zoom out">−</button>
      <button onClick={() => actions.current?.reset()} disabled={!scene || error}>Reset view</button>
      <button onClick={() => actions.current?.zoom(.85)} disabled={!scene || error} aria-label="Zoom in">+</button>
    </div>}
  </div>;
}
