import { useEffect, useState, type CSSProperties, type FormEvent } from 'react';
import type { Preset, ScanResponse } from '../types';
import type { LiveCamera } from '../hooks/useLiveCamera';
import { CameraFeed } from './CameraFeed';
import { SceneViewer } from './SceneViewer';

interface Props {
  camera: LiveCamera;
  active: boolean; scan?: ScanResponse; busy: boolean; error: string;
  health: 'checking' | 'online' | 'offline';
  onScan(name: string, preset: Preset): void; onOpen(): void; onCheckHealth(): void;
}

export function Dashboard({ camera, active, scan, busy, error, health, onScan, onOpen, onCheckHealth }: Props) {
  const groups = new Map<string, { kind: string; count: number; confidence: number }>();
  camera.detections.forEach(item => {
    const group = groups.get(item.label) || { kind: item.label, count: 0, confidence: 0 };
    group.count++; group.confidence = Math.max(group.confidence, item.confidence);
    groups.set(item.label, group);
  });
  const detections = [...groups.values()];
  const [name, setName] = useState('Level 01 / Operations model');
  const [preset, setPreset] = useState<Preset>('office');
  const [clock, setClock] = useState(new Date());
  useEffect(() => { const timer = setInterval(() => setClock(new Date()), 1000); return () => clearInterval(timer); }, []);
  const submit = (event: FormEvent) => { event.preventDefault(); if (!busy) onScan(name.trim(), preset); };
  return <section className={`view dashboard-view ${active ? 'is-active' : ''}`} aria-label="Spatial intelligence dashboard" aria-hidden={!active} inert={!active}>
    <header className="topbar frame-corners">
      <div className="brand-lockup"><div className="brand-mark" aria-hidden="true"><span /><span /><span /></div><div><p className="eyebrow">Field system / Demo workspace</p><h1>Spatial Intelligence</h1></div></div>
      <div className="status-cluster"><button className={`connection-state ${health}`} onClick={onCheckHealth} title="Check API connection"><span className="status-dot" />{health === 'online' ? 'API connected' : health === 'offline' ? 'API offline · retry' : 'Connecting'}</button><time id="missionClock">{clock.toLocaleTimeString('en-US', { hour12: false })}</time></div>
    </header>
    <form className="scan-controls" onSubmit={submit} aria-label="Start a demo scan">
      <label>Scan name<input value={name} onChange={e => setName(e.target.value)} required maxLength={80} disabled={busy} /></label>
      <label>Sample capture<select value={preset} onChange={e => setPreset(e.target.value as Preset)} disabled={busy}><option value="office">Operations room</option><option value="corridor">East corridor</option></select></label>
      <button className="primary-action scan-button" type="submit" disabled={busy || !name.trim()}>{busy ? 'Processing scan…' : error ? 'Retry demo scan' : 'Run demo scan'}<span aria-hidden="true">{busy ? '◌' : '↗'}</span></button>
    </form>
    <div className={`scan-feedback ${error ? 'has-error' : ''}`} role={error ? 'alert' : 'status'} aria-live="polite" aria-busy={busy}>
      {error || (busy ? 'Processing the sample capture. Waiting for the reconstruction response…' : scan ? `${scan.message} Scan ${scan.id.slice(0, 8)} · ${scan.stats.objects} objects returned.` : 'Run a demo scan for the 3D scene, or start your camera for live detections.')}
      {error && scan && <span> Your previous successful scan is still displayed.</span>}
    </div>
    <div className="dashboard-grid">
      <section className="panel camera-panel" aria-labelledby="camera-title"><div className="panel-heading"><div><span className="panel-index">01</span><h2 id="camera-title">Live camera</h2></div><span className="live-badge">{camera.stream ? 'Live' : 'Offline'}</span></div><CameraFeed camera={camera} /></section>
      <section className="panel environment-panel" aria-labelledby="environment-title">
        <div className="panel-heading"><div><span className="panel-index">02</span><h2 id="environment-title">3D environment</h2></div><button className="expand-button" onClick={onOpen} aria-label="Open the full 3D modeling environment">↗</button></div>
        <SceneViewer scene={scan?.scene} active={active} mode="preview" onOpen={onOpen} />
        <div className="environment-meta"><span>Drag to rotate</span><span>Scroll to zoom</span></div>
        <button className="open-cue" onClick={onOpen}>Enter model <span aria-hidden="true">↗</span></button>
      </section>
      <section className="panel detections-panel" data-testid="live-detections" aria-labelledby="detections-title"><div className="panel-heading compact"><div><span className="panel-index">03</span><h2 id="detections-title">Detections</h2></div><span className="muted">{camera.stream ? `${camera.detections.length} visible · live` : 'Camera offline'}</span></div>
        <div className="detection-list">{detections.length ? detections.map(d => <div key={d.kind}><span className={`object-icon ${d.kind}-icon`} /><strong className="capitalize">{d.kind}</strong><em>{String(d.count).padStart(2, '0')}</em><div><i style={{ '--value': `${d.confidence * 100}%` } as CSSProperties} /></div><b>{Math.round(d.confidence * 100)}%</b></div>) : <p className="empty-copy">{camera.stream ? camera.updatedAt ? 'No supported objects in this frame.' : 'Waiting for live detection results…' : 'Start the camera to see live object labels and confidence.'}</p>}</div>
      </section>
      <section className="panel spatial-panel" aria-labelledby="spatial-title"><div className="panel-heading compact"><div><span className="panel-index">04</span><h2 id="spatial-title">Spatial model</h2></div><span className="sync-state">{busy ? 'Processing' : scan ? 'Scan complete' : 'No scan yet'}</span></div>
        <div className="model-stats">
          <article><span>Rooms mapped</span><strong>{scan?.stats.rooms_mapped ?? '—'}</strong><small>{scan ? scan.scene.rooms[0]?.name : 'Awaiting scan'}</small></article>
          <article><span>Objects</span><strong data-testid="object-count">{scan?.stats.objects ?? '—'}</strong><small>{scan ? `${scan.detections.length} classes` : 'No detections'}</small></article>
          <article><span>Frames</span><strong>{scan?.stats.frames ?? '—'}</strong><small>{scan ? `${scan.stats.keyframes} keyframes` : 'Sample capture'}</small></article>
          <article className="coverage-stat"><span>Coverage</span><strong>{scan?.stats.coverage_percent ?? 0}%</strong><div className="coverage-ring" aria-label={`Coverage ${scan?.stats.coverage_percent ?? 0} percent`} style={{ '--coverage': scan?.stats.coverage_percent ?? 0 } as CSSProperties}><span>{scan?.stats.coverage_percent ?? '—'}</span></div><small>Demo coverage</small></article>
        </div>
      </section>
    </div>
  </section>;
}
