import { useState } from 'react';
import type { ScanResponse } from '../types';
import type { LiveCamera } from '../hooks/useLiveCamera';
import { CameraFeed } from './CameraFeed';
import { SceneViewer } from './SceneViewer';

const agents = [
  ['PF', 'Pathfinder', 'Explore possible routes'],
  ['SA', 'Scene analyst', 'Understand scene structure'],
  ['PL', 'Planner', 'Simulate movement options'],
  ['AN', 'Annotator', 'Label rooms and objects'],
];

export function Modeler({ camera, active, scan, onBack }: { camera: LiveCamera; active: boolean; scan?: ScanResponse; onBack(): void }) {
  const [collapsed, setCollapsed] = useState(false);
  const [feedHidden, setFeedHidden] = useState(false);
  const [notice, setNotice] = useState('');
  const exportScene = () => {
    if (!scan) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(scan, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url; link.download = `spatial-scan-${scan.id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice('Scan JSON exported with geometry, detections, and metadata.');
  };
  return <section className={`view modeler-view ${active ? 'is-active' : ''}`} aria-label="3D modeling environment" aria-hidden={!active} inert={!active}>
    <header className="modeler-topbar">
      <button className="icon-button back-button" onClick={onBack} aria-label="Return to dashboard">←</button>
      <div className="model-title"><span className="status-dot" /><div><p>{scan ? 'Demo reconstruction / meters' : 'Workspace / awaiting scan'}</p><h1>{scan?.name || 'Your spatial model'}</h1></div></div>
      <div className="model-actions"><span className="saved-state">{scan ? `Scan ${scan.id.slice(0, 8)} · session only` : 'No model loaded'}</span><button className="primary-action" onClick={exportScene} disabled={!scan}>Export JSON</button></div>
    </header>
    <div className="modeler-workspace">
      <SceneViewer scene={scan?.scene} active={active} mode="modeler" /><div className="model-grid" aria-hidden="true" />
      <aside className="floating-panel feed-float"><div className="float-heading"><span>{camera.stream ? 'Live feed' : 'Camera offline'}</span><button onClick={() => setFeedHidden(!feedHidden)} aria-label={feedHidden ? 'Expand camera feed' : 'Minimize camera feed'} aria-expanded={!feedHidden}>{feedHidden ? '+' : '−'}</button></div>{!feedHidden && <CameraFeed camera={camera} compact />}</aside>
      <aside className="floating-panel tools-float" aria-label="3D render tools"><div className="float-heading"><span>Render tools</span></div><div className="tool-list" role="toolbar" aria-label="Model tools"><button className="is-selected" aria-pressed="true" title="Drag the scene to orbit, scroll to zoom"><span aria-hidden="true">◎</span><span>Orbit</span></button>{['Move', 'Rotate', 'Measure', 'Annotate'].map(tool => <button key={tool} disabled title={`${tool} editing is planned for the next layer`} aria-label={`${tool} — coming soon`}><span aria-hidden="true">◇</span><span>{tool}</span></button>)}</div><p className="tool-note">Scene editing coming next</p></aside>
      {scan && <div className="scene-caption">{scan.scene.rooms.map(r => r.name).join(' · ')} <span>{scan.stats.objects} objects · simulated</span></div>}
      <section className={`agent-dock ${collapsed ? 'is-collapsed' : ''}`} aria-labelledby="agent-title"><div className="agent-heading"><div><span className="panel-index">AI</span><div><h2 id="agent-title">Agent toolbox</h2><p>Scene-aware assistance · coming soon</p></div></div><button onClick={() => setCollapsed(!collapsed)} aria-expanded={!collapsed}>{collapsed ? 'Expand' : 'Collapse'}</button></div><div className="agent-cards" inert={collapsed}>{agents.map(([initials, name, description]) => <button key={name} disabled title="Agent processing is not connected yet"><span className="agent-icon">{initials}</span><div><strong>{name}</strong><small>{description}</small></div><em>Planned</em></button>)}</div></section>
      {notice && <div className="toast is-visible" role="status" onClick={() => setNotice('')}>{notice}</div>}
    </div>
  </section>;
}
