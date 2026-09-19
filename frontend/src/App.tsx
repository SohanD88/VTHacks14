import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveCamera } from "./hooks/useLiveCamera";
import { Dashboard } from "./components/Dashboard";
import { Modeler } from "./components/Modeler";
import { api } from "./services/api";
import type { Mode, ScanResponse } from "./types";
export function App() {
  const camera = useLiveCamera();
  const [view, setView] = useState(
    location.hash === "#modeler" ? "modeler" : "dashboard",
  );
  const [scan, setScan] = useState<ScanResponse>();
  const [recent, setRecent] = useState<ScanResponse[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<"checking" | "online" | "offline">(
    "checking",
  );
  const upload = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    try {
      setRecent(await api.list());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  const checkHealth = useCallback(async () => {
    try {
      await api.health();
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
    void api
      .getScan(encodeURIComponent(id))
      .then((result) => {
        if (alive) setScan((current) => current ?? result);
      })
      .catch((e: Error) => {
        if (!alive) return;
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
    try {
      setScan(await api.getScan(id));
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
  const imported = (result: ScanResponse) => {
    setScan(result);
    setError("");
    void refresh();
  };
  return (
    <main className={`app-shell ${view === "modeler" ? "is-modeling" : ""}`}>
      <Dashboard
        camera={camera}
        active={view === "dashboard"}
        scan={scan}
        recent={recent}
        uploading={uploading}
        busy={!!running || uploading}
        error={error}
        health={health}
        onScan={run}
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
        scan={scan}
        onChange={imported}
        onBack={() => navigate("dashboard")}
      />
    </main>
  );
}
