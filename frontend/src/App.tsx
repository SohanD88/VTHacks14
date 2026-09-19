import { useCallback, useEffect, useRef, useState } from 'react';
import { Dashboard } from './components/Dashboard';
import { Modeler } from './components/Modeler';
import { api, ApiError } from './services/api';
import type { Preset, ScanResponse } from './types';

export function App() {
  const [view, setView] = useState(location.hash === '#modeler' ? 'modeler' : 'dashboard');
  const [scan, setScan] = useState<ScanResponse>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>('checking');
  const pending = useRef<AbortController | null>(null);
  const checkHealth = useCallback(async (signal?: AbortSignal) => {
    setHealth('checking');
    try { await api.health(signal); if (!signal?.aborted) setHealth('online'); }
    catch { if (!signal?.aborted) setHealth('offline'); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void checkHealth(controller.signal);
    return () => { controller.abort(); pending.current?.abort(); };
  }, [checkHealth]);
  const navigate = useCallback((next: 'dashboard' | 'modeler') => {
    history.pushState(null, '', next === 'modeler' ? '#modeler' : location.pathname + location.search);
    setView(next);
  }, []);
  useEffect(() => {
    const sync = () => setView(location.hash === '#modeler' ? 'modeler' : 'dashboard');
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && location.hash === '#modeler') navigate('dashboard'); };
    window.addEventListener('popstate', sync); window.addEventListener('hashchange', sync); window.addEventListener('keydown', escape);
    return () => { window.removeEventListener('popstate', sync); window.removeEventListener('hashchange', sync); window.removeEventListener('keydown', escape); };
  }, [navigate]);
  useEffect(() => {
    window.scrollTo(0, 0);
    if (view === 'modeler') document.querySelector<HTMLButtonElement>('.back-button')?.focus();
  }, [view]);
  const runScan = async (name: string, preset: Preset) => {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller; setBusy(true); setError('');
    try {
      const result = await api.createScan({ name, preset, source: 'demo' }, controller.signal);
      setScan(result); setHealth('online');
    } catch (failure) {
      if (!controller.signal.aborted) {
        const message = failure instanceof Error ? failure.message : 'Scan failed. Please try again.';
        setError(failure instanceof ApiError && failure.requestId ? `${message} Reference: ${failure.requestId}` : message);
        if (failure instanceof ApiError && failure.status === 0) setHealth('offline');
      }
    } finally { pending.current = null; setBusy(false); }
  };
  return <main className={`app-shell ${view === 'modeler' ? 'is-modeling' : ''}`}>
    <Dashboard active={view === 'dashboard'} scan={scan} busy={busy} error={error} health={health} onScan={runScan} onOpen={() => navigate('modeler')} onCheckHealth={() => void checkHealth()} />
    <Modeler active={view === 'modeler'} scan={scan} onBack={() => navigate('dashboard')} />
  </main>;
}
