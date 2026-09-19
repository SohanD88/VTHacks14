export function CameraFeed({ compact = false }: { compact?: boolean }) {
  if (compact) return <><div className="mini-feed"><span className="sample-caption">Demo capture source</span><div className="scanline" /></div><div className="feed-stats"><span>SIMULATED</span><span>CAMERA NOT CONNECTED</span></div></>;
  return <div className="camera-feed" aria-label="Simulated camera placeholder">
    <div className="camera-room"><span className="room-edge edge-a" /><span className="room-edge edge-b" /><span className="room-edge edge-c" /><span className="room-edge edge-d" /></div>
    <div className="camera-placeholder"><span className="empty-cube">◎</span><strong>Ready for a new perspective</strong><p>Choose a sample capture to begin.<br />Live camera capture is coming next.</p></div>
    <div className="camera-hud"><span>DEMO SOURCE</span><span>NO LIVE CAMERA</span></div><div className="scanline" />
  </div>;
}
