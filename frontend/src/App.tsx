import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveCamera } from "./hooks/useLiveCamera";
import { Dashboard } from "./components/Dashboard";
import { Modeler } from "./components/Modeler";
import { api } from "./services/api";
import type { HealthResponse, Mode, ScanResponse } from "./types";
export function App() {
  const camera = useLiveCamera();
  const [view, setView] = useState(
    location.hash === "#modeler" ? "modeler" : "dashboard",
  );
  const [scan, setScan] = useState<ScanResponse>();
  const [recent, setRecent] = useState<ScanResponse[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<"checking" | "online" | "offline">(
    "checking",
  );
  const [blender, setBlender] = useState<HealthResponse["blender"]>();
  const upload = useRef<AbortController | null>(null);
  const selectionVersion = useRef(0);
  const clearPreview = useCallback(() => {
    selectionVersion.current += 1;
    setScan(undefined);
    setError("");
    const url = new URL(location.href);
    url.searchParams.delete("scan");
    history.replaceState(null, "", url);
  }, []);
  const refresh = useCallback(async () => {
    try {
      setRecent(await api.list());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  const checkHealth = useCallback(async () => {
    try {
      setBlender((await api.health()).blender);
      setHealth("online");
      setError("");
      await refresh();
    } catch {
      setHealth("offline");
    }
  }, [refresh]);
  useEffect(() => {
    void checkHealth();
    return () => upload.current?.abort();
  }, [checkHealth, refresh]);
  // Keep the selected scan in the URL so reloading the Sandbox restores it.
  useEffect(() => {
    const id = new URL(location.href).searchParams.get("scan");
    if (!id) return;
    let alive = true;
    const version = selectionVersion.current;
    void api
      .getScan(encodeURIComponent(id))
      .then((result) => {
        if (alive && version === selectionVersion.current)
          setScan((current) => current ?? result);
      })
      .catch((e: Error) => {
        if (!alive || version !== selectionVersion.current) return;
        setError(e.message);
        setView("dashboard");
        const url = new URL(location.href);
        url.searchParams.delete("scan");
        url.hash = "";
        history.replaceState(null, "", url);
      });
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!scan) return;
    const url = new URL(location.href);
    url.searchParams.set("scan", scan.id);
    history.replaceState(null, "", url);
  }, [scan?.id]);
  const navigate = useCallback((next: "dashboard" | "modeler") => {
    history.pushState(
      null,
      "",
      next === "modeler" ? "#modeler" : location.pathname + location.search,
    );
    setView(next);
  }, []);
  useEffect(() => {
    const sync = () =>
      setView(location.hash === "#modeler" ? "modeler" : "dashboard");
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("hashchange", sync);
    };
  }, []);
  const running = scan?.status === "queued" || scan?.status === "processing";
  useEffect(() => {
    if (!running || !scan) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const status = await api.status(scan.id);
        if (!alive) return;
        setError("");
        if (status.status === "queued" || status.status === "processing") {
          setScan((previous) =>
            previous?.id === status.id ? { ...previous, ...status } : previous,
          );
          timer = setTimeout(poll, 1000);
        } else {
          const result = await api.getScan(scan.id);
          if (alive) {
            setScan(result);
            void refresh();
          }
        }
      } catch (e) {
        if (alive) {
          setError((e as Error).message);
          timer = setTimeout(poll, 3000);
        }
      }
    };
    timer = setTimeout(poll, 500);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [scan?.id, running, refresh]);
  const run = async (
    file: File,
    name: string,
    mode: Mode,
    source: "video" | "capture",
  ) => {
    if (uploading || running) return;
    clearPreview();
    setUploading(true);
    setError("");
    const controller = new AbortController();
    upload.current = controller;
    try {
      const result = await api.upload(
        file,
        name,
        mode,
        source,
        controller.signal,
      );
      setScan(result);
      setHealth("online");
      void refresh();
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
      else
        setError("Upload cancelled. You can submit the selected video again.");
    } finally {
      setUploading(false);
      upload.current = null;
    }
  };
  const select = async (id: string) => {
    setError("");
    const version = ++selectionVersion.current;
    try {
      const result = await api.getScan(id);
      if (version === selectionVersion.current) setScan(result);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const cancel = async () => {
    try {
      if (upload.current) upload.current.abort();
      else if (scan) await api.cancel(scan.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const loadDemo = async () => {
    if (uploading || running || loadingDemo) return;
    setLoadingDemo(true);
    setError("");
    try {
      const result = await api.loadDemo();
      setScan(result);
      setHealth("online");
      await refresh();
      navigate("modeler");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingDemo(false);
    }
  };
  const imported = (result: ScanResponse) => {
    setScan(result);
    setError("");
    void refresh();
  };
  // A worker can attach scene data before its final stage. Only publish it
  // after a successful completion, including when restoring an in-flight scan.
  const sceneReady =
    !uploading &&
    !loadingDemo &&
    (scan?.status === "completed" || scan?.status === "degraded");
  const visibleScan = scan && !sceneReady ? { ...scan, scene: null } : scan;
  return (
    <main className={`app-shell ${view === "modeler" ? "is-modeling" : ""}`}>
      <Dashboard
        camera={camera}
        active={view === "dashboard"}
        scan={visibleScan}
        recent={recent}
        uploading={uploading}
        busy={!!running || uploading || loadingDemo}
        loadingDemo={loadingDemo}
        onLoadDemo={() => void loadDemo()}
        error={error}
        health={health}
        blender={blender}
        onScan={run}
        onInputChange={clearPreview}
        onCancel={() => void cancel()}
        onSelect={(id) => void select(id)}
        onDelete={async (id) => {
          try {
            await api.delete(id);
            if (scan?.id === id) {
              setScan(undefined);
              const url = new URL(location.href);
              url.searchParams.delete("scan");
              history.replaceState(null, "", url);
            }
            void refresh();
          } catch (e) {
            setError((e as Error).message);
          }
        }}
        onOpen={() => navigate("modeler")}
        onCheckHealth={() => void checkHealth()}
      />
      <Modeler
        camera={camera}
        active={view === "modeler"}
        scan={visibleScan}
        onChange={imported}
        onBack={() => navigate("dashboard")}
      />
    </main>
  );
}
