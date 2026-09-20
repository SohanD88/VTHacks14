import { useEffect, useRef, useState } from "react";
import type {
  RouteEndpoint,
  ScanResponse,
  SceneRoute,
  Vector3,
} from "../types";
import { api } from "../services/api";

export function useSceneRoute(
  scan: ScanResponse | undefined,
  disabled: boolean,
) {
  const [start, setStart] = useState<RouteEndpoint>();
  const [end, setEnd] = useState<RouteEndpoint>();
  const [picking, setPicking] = useState<"start" | "end">();
  const [result, setResult] = useState<SceneRoute>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | undefined>(undefined);
  const current = useRef({ scan, disabled });
  current.current = { scan, disabled };

  const invalidate = () => {
    pending.current?.abort();
    pending.current = undefined;
    setResult(undefined);
    setBusy(false);
    setError("");
  };
  const clear = () => {
    invalidate();
    setStart(undefined);
    setEnd(undefined);
    setPicking(undefined);
  };
  useEffect(() => {
    clear();
    return () => pending.current?.abort();
  }, [scan?.id, scan?.revision, scan?.scene, disabled]);

  const choose = (which: "start" | "end", endpoint?: RouteEndpoint) => {
    invalidate();
    (which === "start" ? setStart : setEnd)(endpoint);
    setPicking(undefined);
  };
  const pickPoint = (point: Vector3, objectId: string) => {
    if (!picking || disabled) return;
    const object = scan?.scene?.objects.find((o) => o.id === objectId);
    if (
      object?.entrance ||
      ["door", "doorway", "entrance", "exit", "opening"].includes(
        object?.kind ?? "",
      )
    ) {
      choose(picking, { object_id: objectId });
    } else if (object?.kind === "floor") {
      choose(picking, { point });
    } else {
      setError("Click a floor surface or a doorway to place this point.");
    }
  };
  const calculate = async () => {
    if (!scan?.scene || !start || !end || disabled) return;
    invalidate();
    setPicking(undefined);
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    try {
      const route = await api.route(
        scan.id,
        scan.revision,
        start,
        end,
        controller.signal,
      );
      if (
        pending.current !== controller ||
        current.current.disabled ||
        current.current.scan?.id !== scan.id ||
        current.current.scan?.revision !== scan.revision ||
        current.current.scan?.scene !== scan.scene
      )
        return;
      setResult(route);
    } catch (e) {
      if (pending.current === controller && !controller.signal.aborted)
        setError((e as Error).message);
    } finally {
      if (pending.current === controller) {
        pending.current = undefined;
        setBusy(false);
      }
    }
  };
  return {
    start,
    end,
    picking,
    result,
    busy,
    error,
    choose,
    pickPoint,
    calculate,
    clear,
    pick: (which: "start" | "end") => {
      invalidate();
      setPicking(which);
    },
    cancelPick: () => setPicking(undefined),
  };
}
