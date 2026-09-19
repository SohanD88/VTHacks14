import { useEffect, useState, useSyncExternalStore } from 'react';
import { LiveCameraSession } from '../services/liveCamera';

export function useLiveCamera() {
  const [session] = useState(() => new LiveCameraSession());
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot);
  useEffect(() => {
    const stop = () => session.stop();
    window.addEventListener('pagehide', stop);
    return () => { window.removeEventListener('pagehide', stop); stop(); };
  }, [session]);
  return { ...state, start: session.start, stop: session.stop, retry: session.retry,
    rotate: session.rotate, selectSource: session.selectSource, setGlassesUrl: session.setGlassesUrl,
    previewFailed: session.previewFailed };
}
export type LiveCamera = ReturnType<typeof useLiveCamera>;
