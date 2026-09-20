import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveCamera } from "./useLiveCamera";

/**
 * Follows and controls recording on the glasses rig (backend/glassesFiles/tap_stream.py).
 *
 * The rig records when its Arduino touch sensor is tapped. This hook polls the rig's
 * /status so the dashboard shows that state, lets the dashboard's own buttons call
 * /start and /stop, and, when a recording finishes, downloads the saved video and hands
 * it to the dashboard as the capture to reconstruct. It stays silent if the rig is not
 * running or is an older version without these endpoints.
 */
interface RigMission {
  name: string;
  video: string;
  bytes?: number;
}
interface RigStatus {
  camera: boolean;
  active: boolean;
  elapsed: number;
  tap_seq: number;
  last_mission?: RigMission | null;
}
export interface GlassesRecorder {
  /** tap_stream.py answered /status, so start/stop can be used. */
  available: boolean;
  recording: boolean;
  elapsed: number;
  /** Short progress note, e.g. while the finished video is being loaded. */
  message: string;
  error: string;
  start(): void;
  stop(): void;
}

const MAX_BYTES = 250 * 1024 ** 2; // same limit the upload form enforces
const POLL_MS = 1000;

function rigOrigin(address: string): string | null {
  try {
    const url = new URL(address.trim());
    return ["http:", "https:"].includes(url.protocol) ? url.origin : null;
  } catch {
    return null;
  }
}

async function readStatus(
  origin: string,
  signal: AbortSignal,
): Promise<RigStatus | null> {
  try {
    const response = await fetch(`${origin}/status`, {
      cache: "no-store",
      signal,
    });
    if (
      !response.ok ||
      !(response.headers.get("content-type") ?? "").includes("json")
    )
      return null;
    const value = (await response.json()) as Partial<RigStatus>;
    return typeof value.active === "boolean" &&
      typeof value.camera === "boolean"
      ? (value as RigStatus)
      : null;
  } catch {
    return null;
  }
}

export function useGlassesRecorder(
  camera: LiveCamera,
  onCaptured: (file: File) => void,
): GlassesRecorder {
  const [available, setAvailable] = useState(false);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const captured = useRef(onCaptured);
  captured.current = onCaptured;

  const enabled = camera.source === "glasses" && camera.active;
  const origin = enabled ? rigOrigin(camera.glassesUrl) : null;

  useEffect(() => {
    if (!origin) {
      setAvailable(false);
      setRecording(false);
      setElapsed(0);
      setMessage("");
      setError("");
      return;
    }
    const abort = new AbortController();
    let stopped = false;
    let timer = 0;
    // Missions that finished before the dashboard connected are not imported.
    let handled: string | null | undefined;

    const load = async (mission: RigMission) => {
      setMessage("Loading the glasses recording…");
      setError("");
      try {
        if ((mission.bytes ?? 0) > MAX_BYTES)
          throw new Error("The glasses recording is larger than 250 MB.");
        const response = await fetch(`${origin}${mission.video}`, {
          cache: "no-store",
          signal: abort.signal,
        });
        if (!response.ok)
          throw new Error(`The glasses rig returned ${response.status}.`);
        const blob = await response.blob();
        if (!blob.size || blob.size > MAX_BYTES)
          throw new Error("The glasses recording is empty or over 250 MB.");
        if (stopped) return;
        captured.current(
          new File([blob], `${mission.name}.mp4`, { type: "video/mp4" }),
        );
        setMessage("");
      } catch (e) {
        if (stopped) return;
        setMessage("");
        setError(
          `Could not load the glasses recording. ${(e as Error).message} It is still saved on the glasses computer.`,
        );
      }
    };

    const poll = async () => {
      const status = await readStatus(origin, abort.signal);
      if (stopped) return;
      setAvailable(status?.camera === true);
      setRecording(status?.camera === true && status.active);
      setElapsed(status?.camera === true && status.active ? status.elapsed : 0);
      if (status?.camera) {
        const last = status.last_mission ?? null;
        if (handled === undefined) handled = last?.name ?? null;
        else if (!status.active && last && last.name !== handled) {
          handled = last.name;
          await load(last);
        }
        if (status.active) setError("");
      }
      if (!stopped) timer = window.setTimeout(poll, POLL_MS);
    };
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [origin]);

  const send = useCallback(
    (path: "/start" | "/stop") => {
      if (!origin) return;
      fetch(`${origin}${path}`, { cache: "no-store" })
        .then((response) => {
          if (!response.ok)
            throw new Error(`The rig returned ${response.status}.`);
          setRecording(path === "/start");
          setError("");
        })
        .catch((cause) =>
          setError(
            `The glasses rig did not accept the command. ${(cause as Error).message}`,
          ),
        );
    },
    [origin],
  );
  const start = useCallback(() => send("/start"), [send]);
  const stop = useCallback(() => send("/stop"), [send]);

  return { available, recording, elapsed, message, error, start, stop };
}

/**
 * "Computer webcam" source: the browser owns the camera, so the rig script runs in
 * button-only mode (`python tap_stream.py --camera none`) and just counts Arduino taps
 * in /status "tap_seq". This hook calls `onTap` once for every new tap, so the dashboard
 * can start and stop its own recording from the physical button. Silent when the script
 * is not running.
 */
export function useRigTaps(camera: LiveCamera, onTap: () => void): boolean {
  const [connected, setConnected] = useState(false);
  const tap = useRef(onTap);
  tap.current = onTap;

  const enabled = camera.source === "computer" && camera.active;
  const origin = enabled ? rigOrigin(camera.glassesUrl) : null;

  useEffect(() => {
    if (!origin) {
      setConnected(false);
      return;
    }
    const abort = new AbortController();
    let stopped = false;
    let timer = 0;
    let seen: number | undefined; // taps from before we connected are ignored

    const poll = async () => {
      let value: { camera?: unknown; tap_seq?: unknown } | null = null;
      try {
        const response = await fetch(`${origin}/status`, {
          cache: "no-store",
          signal: abort.signal,
        });
        if (
          response.ok &&
          (response.headers.get("content-type") ?? "").includes("json")
        )
          value = (await response.json()) as {
            camera?: unknown;
            tap_seq?: unknown;
          };
      } catch {
        value = null;
      }
      if (stopped) return;
      const seq =
        value?.camera === false && typeof value.tap_seq === "number"
          ? value.tap_seq
          : null;
      setConnected(seq !== null);
      if (seq !== null) {
        if (seen !== undefined && seq > seen) tap.current(); // one action per poll, even for a double tap
        seen = seq;
      } else seen = undefined;
      // Fast while the rig answers (a tap should feel instant), slow while it does not.
      timer = window.setTimeout(poll, seq !== null ? 250 : 2500);
    };
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [origin]);

  return connected;
}
