"""
tap_stream.py  v5  -  runs on the computer connected to the glasses webcam.

The camera streams whenever it is connected. Tap to start recording a mission;
tap again to stop recording. Live viewing and detection continue between missions.

  Touch sensor 1 (socket D2, sends TAP1) = start / stop the mission
  Touch sensor 2 (socket D3, sends TAP2) = drop a "hazard" marker

v5.1: works with tap_buttons.ino v3. That sketch learns whether each sensor or
  button rests LOW or HIGH, so a part that rests HIGH (D2 stuck at 1 with the
  old sketch) now starts and stops recording the moment it is pressed.

WHY v5  (make it look like the Windows Camera app)
  The Windows Camera app looks perfect because it runs the webcam in its native
  compressed mode (MJPG) at 1080p / 30 fps with everything on automatic.
  v5 does the same:
    - asks for 1920x1080 MJPG at 30 fps by default, and MEASURES that it really
      gets it (falls back to 720p, then 480p, only if the camera cannot deliver)
    - leaves autofocus, auto exposure and auto white balance ON, and undoes the
      manual focus / shutter settings that earlier versions of this script set
    - saved video + keyframes are full 1080p. The live view is 1280 px at high
      JPEG quality by default; the Ultra button sends the full 1080p picture.
  CLOSE the Windows Camera app before running this. Two apps cannot share the camera.

WHY v4  (the real cause of the 720p lag)
  On Windows, OpenCV's DirectShow code forgets the MJPG request as soon as the
  size or frame rate is set after it, and silently falls back to raw YUY2 video.
  Raw 720p only reaches about 10 fps over USB. v2 and v3 set MJPG FIRST, so the
  camera was never really in MJPG mode at 720p. v4 sets size, then fps, then
  MJPG LAST, then MEASURES the real frame rate before starting, and falls back
  by itself if the camera still cannot keep up.

WHY v3
  v2 did everything in one loop: read camera -> save video -> score and save
  keyframes -> encode the live picture. At 720p that loop could not finish
  inside one frame (33 ms), and every keyframe save (twice a second) stalled
  the live picture. That is the lag and stutter you saw.

  v3 splits the work into three threads that run in parallel:
    capture   only reads the camera, as fast as it delivers
    stream    always encodes the NEWEST frame, so the live view never queues up
    recorder  saves video + keyframes from its own queue, can never stall the view
  The web stream now wakes up exactly when a new frame exists, skips frames
  for slow viewers instead of falling behind, and keeps network buffers small.

  The test page now has live controls:
    Shutter buttons  - lock a fast shutter. This is the fix for smearing and
                       "warping" when you move. Lower number = sharper but darker.
    Stream presets   - Sharp / Balanced / Light (use Light over a weak hotspot)
    Camera settings  - opens the Windows camera settings window

Install once:
    python -m pip install opencv-python flask pyserial

Run:
    python tap_stream.py --camera 1 --rotate ccw

-------------------------------------------------------------------------
FOR THE UI TEAM  (all endpoints allow cross-origin requests)

  Live video:   <img src="http://127.0.0.1:8080/stream">
      Remains live before, during, and after a recording mission.
      If the backpack script restarts, reset the img src
      (img.src = url + '?' + Date.now()). /status "boot" changes on restart.
  Single newest frame as a JPEG:   GET /frame.jpg

  GET /status   -> {"active", "mission", "elapsed", "frames", "keyframes",
                    "arduino", "sketch", "pins", "boot", "version",
                    "cam_fps", "enc_fps", "sent_fps", "rec_fps", "rec_dropped", ...}
  GET /events   -> [{"t": 8.2, "keyframe": 16, "label": "hazard", ...}, ...]
  GET /toggle   -> start or stop (same as tapping sensor 1)
  GET /start    /stop
  GET /mark?label=hazard        -> drop a marker from the UI
  GET /tune?preset=light|balanced|sharp     (or max=720&fps=30&q=70)
  GET /camera?exposure=-6   |  exposure=auto  |  gain=120  |  settings=1
-------------------------------------------------------------------------
"""

import argparse
import csv
import logging
import os
import queue
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")   # avoids a very slow camera open with --backend msmf
import cv2
from flask import Flask, Response, jsonify, request

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None

VERSION = "v5.1"

ROTATIONS = {
    "none": None,
    "cw": cv2.ROTATE_90_CLOCKWISE,
    "ccw": cv2.ROTATE_90_COUNTERCLOCKWISE,
    "180": cv2.ROTATE_180,
}

PRESETS = {
    "light":    {"max": 480,  "fps": 15.0, "q": 60},   # weak hotspot
    "balanced": {"max": 854,  "fps": 30.0, "q": 75},   # good wifi
    "sharp":    {"max": 1280, "fps": 30.0, "q": 85},   # same laptop: more pixels than the page can show
    "ultra":    {"max": 1920, "fps": 30.0, "q": 90},   # full 1080p picture, heaviest
}

app = Flask(__name__)
lock = threading.Lock()                  # guards mission state + events
boot_id = str(int(time.time() * 1000))   # changes every time the script starts

shutdown = False        # whole program is exiting
want_active = False     # what the taps / UI asked for
active = False          # a mission is being recorded right now
mission_no = 0

arduino_ok = False      # serial port is open
last_hb = 0.0           # last heartbeat from the sketch
pins = [None, None]     # live state of D2, D3 as reported by the sketch
last_tap1 = 0.0
tap_lockout = 1.0

out_root = Path("recordings")
mission_dir = None
mission_start = 0.0
frame_idx = 0
keyframe_idx = 0
events = []
overlay_text, overlay_until = "", 0.0

tune = dict(PRESETS["sharp"])
stats = {"cam_fps": 0.0, "enc_fps": 0.0, "sent_fps": 0.0, "rec_fps": 0.0,
         "rec_dropped": 0, "enc_ms": 0.0, "rec_ms": 0.0, "clients": 0, "cam_mode": ""}
cam_state = {"live": False, "exposure": "auto", "gain": None, "focus": "auto"}
cam_requests = []       # camera control changes, applied by the capture thread
rec_q = queue.Queue()
rec_limit = 30           # max frames waiting for the recorder (resized to ~200 MB once we know the frame size)


class Latest:
    """Holds only the newest item. Readers sleep until something newer arrives."""

    def __init__(self):
        self.cond = threading.Condition()
        self.item = None
        self.seq = 0
        self.updated_at = 0.0

    def put(self, item):
        with self.cond:
            self.item = item
            self.seq += 1
            self.updated_at = time.time()
            self.cond.notify_all()

    def wait_newer(self, last_seq, timeout=1.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq or shutdown, timeout)
            return self.seq, self.item


raw_box = Latest()      # newest camera frame: (frame, capture_time)
jpeg_box = Latest()     # newest encoded stream frame: bytes


# ------------------------------------------------------------ controls
def toggle(source):
    global want_active
    with lock:
        want_active = not want_active
        state = "START" if want_active else "STOP"
    print(f"[{source}] {state}")


def add_event(label, source):
    global overlay_text, overlay_until
    with lock:
        if not active:
            print(f"[{source}] '{label}' ignored, no mission running")
            return False
        ev = {
            "t": round(time.time() - mission_start, 2),
            "frame": frame_idx,
            "keyframe": keyframe_idx,
            "label": label,
            "source": source,
            "clock": datetime.now().strftime("%H:%M:%S"),
        }
        events.append(ev)
        overlay_text, overlay_until = label.upper().replace("_", " "), time.time() + 2.0
        with open(mission_dir / "events.csv", "a", newline="") as f:
            csv.writer(f).writerow(list(ev.values()))
    print(f"[event] {ev['clock']}  {label}  (t={ev['t']}s, keyframe {ev['keyframe']})")
    return True


# ------------------------------------------------------------ camera
def _fourcc_str(cap):
    cc = int(cap.get(cv2.CAP_PROP_FOURCC))
    txt = "".join(chr((cc >> (8 * i)) & 0xFF) for i in range(4)) if cc > 0 else ""
    return txt.strip() or "?"


def _apply_mode(cap, w, h, fps):
    """ORDER MATTERS on Windows/DirectShow: size, then fps, then MJPG LAST.
    Setting the size or fps after the fourcc makes OpenCV rebuild the camera
    pipeline with no fourcc, which lands on raw YUY2 (checked in OpenCV's source)."""
    mjpg = cv2.VideoWriter_fourcc(*"MJPG")
    if os.name != "nt":
        cap.set(cv2.CAP_PROP_FOURCC, mjpg)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_FOURCC, mjpg)          # LAST. Do not set size/fps after this.


def _measure_fps(cap, seconds=1.2, warm=6):
    for _ in range(warm):                        # first frames after a mode change are slow
        cap.read()
    n, t0 = 0, time.time()
    while time.time() - t0 < seconds:
        ok, _ = cap.read()
        if ok:
            n += 1
        else:
            time.sleep(0.01)
    return n / max(1e-6, time.time() - t0)


def negotiate(cap, width, height, want_fps, exposure_locked=False):
    """Try camera modes, best first, until one REALLY delivers the frame rate."""
    attempts = [(width, height, want_fps)]
    if want_fps > 30:
        attempts.append((width, height, 30.0))
    for w, h in ((1920, 1080), (1280, 720), (640, 480)):      # step down only if we have to
        if w * h < width * height:
            attempts.append((w, h, 30.0))

    results = []
    for w, h, fps in attempts:
        _apply_mode(cap, w, h, fps)
        got = _measure_fps(cap)
        mode = f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} {_fourcc_str(cap)}"
        print(f"[camera] asked {w}x{h} @ {fps:.0f} -> got {mode}, measured {got:.1f} fps")
        res = {"w": w, "h": h, "fps": fps, "mode": mode, "got": got, "locked": None}
        results.append(res)
        if got >= 0.8 * fps:
            return res

        # Right format but still slow = the auto shutter is running long because the room
        # is dim. A locked shutter (1/32 s) cannot drag the frame rate down.
        if got >= 1 and "MJPG" in mode.upper() and not exposure_locked:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
            cap.set(cv2.CAP_PROP_EXPOSURE, -5)
            got2 = _measure_fps(cap, warm=10)
            print(f"[camera]   dim room? locked shutter at -5 -> measured {got2:.1f} fps")
            if got2 >= 0.8 * fps:
                res.update(got=got2, locked=-5.0)
                return res
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)   # did not help, back to auto

    best = max(results, key=lambda r: r["got"])      # nothing hit the target: keep the fastest
    if best is not results[-1]:
        _apply_mode(cap, best["w"], best["h"], best["fps"])
    return best


def open_camera(args):
    source = int(args.camera) if str(args.camera).isdigit() else args.camera
    is_file = not isinstance(source, int)
    if is_file:
        return cv2.VideoCapture(source), True

    if os.name == "nt":
        backend = cv2.CAP_MSMF if args.backend == "msmf" else cv2.CAP_DSHOW
        cap = cv2.VideoCapture(source, backend)
    else:
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        return cap, False

    # Start from the same state the Windows Camera app uses: everything automatic.
    # (Earlier versions of this script forced manual focus; that setting can stick in the camera.)
    for prop in (cv2.CAP_PROP_AUTOFOCUS, cv2.CAP_PROP_AUTO_EXPOSURE, cv2.CAP_PROP_AUTO_WB):
        try:
            cap.set(prop, 1)
        except Exception:
            pass

    print("[camera] testing camera modes, takes a few seconds...")
    res = negotiate(cap, args.width, args.height, args.cam_fps, exposure_locked=args.exposure is not None)
    if res["got"] < 1:
        print("ERROR: the camera opened but sends no pictures. Close the Windows Camera app, Zoom, Teams "
              "and any browser tab using the webcam, then run this again.")
        os._exit(1)
    stats["cam_mode"] = res["mode"]
    if res["locked"] is not None:
        cam_state["exposure"] = res["locked"]
    verdict = "good" if res["got"] >= 0.8 * res["fps"] else "SLOW"
    print(f"[camera] RESULT: {res['mode']} at {res['got']:.1f} fps  ({verdict})")
    if verdict == "SLOW" and os.name == "nt" and args.backend != "msmf":
        print("[camera] it never reached full speed. Try adding:  --backend msmf   "
              "(the camera number may be different there, try --camera 0 and 1)")

    # camera controls only. None of these rebuild the pipeline, so MJPG survives.
    if args.exposure is not None:
        cam_requests.append(("exposure", args.exposure))
    if args.gain is not None:
        cam_requests.append(("gain", args.gain))
    if args.lock_focus:
        cam_requests.append(("focus", "lock"))
    if args.settings:
        cam_requests.append(("settings", 1))
    cam_state["live"] = True
    return cap, False


def apply_cam_request(cap, req):
    """Runs inside the capture thread (camera controls must be set from there)."""
    kind, val = req
    try:
        if kind == "exposure":
            if val is None:
                ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
                cam_state["exposure"] = "auto"
                print(f"[camera] shutter -> AUTO ({'ok' if ok else 'camera ignored it, use the settings window'})")
            else:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
                ok = cap.set(cv2.CAP_PROP_EXPOSURE, float(val))
                cam_state["exposure"] = val
                print(f"[camera] shutter locked at {val} ({'ok' if ok else 'camera ignored it'})")
        elif kind == "gain":
            ok = cap.set(cv2.CAP_PROP_GAIN, float(val))
            cam_state["gain"] = val
            print(f"[camera] gain -> {val} ({'ok' if ok else 'camera ignored it'})")
        elif kind == "focus":
            auto = val == "auto"
            ok = cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if auto else 0)   # 0 = hold the focus where it is now
            cam_state["focus"] = "auto" if auto else "locked"
            print(f"[camera] focus -> {cam_state['focus']} ({'ok' if ok else 'camera has no focus control'})")
        elif kind == "settings":
            cap.set(cv2.CAP_PROP_SETTINGS, 1)
            print("[camera] opened the camera settings window (look on the taskbar)")
    except Exception as e:
        print(f"[camera] could not apply {kind}: {e}")


def capture_loop(args):
    """Thread 1: read the camera and nothing else."""
    cap, is_file = open_camera(args)
    if not cap.isOpened():
        print(f"ERROR: could not open camera {args.camera}. Try --camera 0 or --camera 2.")
        os._exit(1)

    rot = ROTATIONS[args.rotate]
    file_fps = cap.get(cv2.CAP_PROP_FPS) if is_file else 0
    file_gap = 1.0 / (file_fps if file_fps and file_fps > 1 else 30.0)
    next_file_t = time.time()
    global rec_limit
    n, t0, windows, reported, last_fail_msg, frame_count, last_drop_msg = 0, None, 0, False, 0.0, 0, 0.0

    print("Camera ready. Live stream available; waiting for a recording tap...")
    while not shutdown:
        while cam_requests:
            req = cam_requests.pop(0)
            if not is_file:
                apply_cam_request(cap, req)

        ok, frame = cap.read()
        if not ok:
            if is_file:                       # loop test videos forever
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            else:
                if time.time() - last_fail_msg > 5:
                    last_fail_msg = time.time()
                    print("[camera] no frames coming in. Is the webcam unplugged or used by another app?")
                time.sleep(0.05)
            continue
        if rot is not None:
            frame = cv2.rotate(frame, rot)
        now = time.time()

        raw_box.put((frame, now))
        frame_count += 1
        if frame_count == 1:
            rec_limit = int(min(60, max(8, 200e6 / frame.nbytes)))
        if active and (stats["cam_fps"] <= 45 or frame_count % 2 == 0):   # 60 fps camera: record every 2nd
            if rec_q.qsize() < rec_limit:
                rec_q.put((mission_no, frame, now))
            else:
                stats["rec_dropped"] += 1
                if now - last_drop_msg > 5:
                    last_drop_msg = now
                    print("[recorder] cannot keep up at this resolution, dropping some frames from the saved "
                          "video (live view is not affected). If it keeps happening run with --width 1280 --height 720")

        # measure what the camera really delivers (clock starts at the first frame)
        if t0 is None:
            t0 = now
        else:
            n += 1
        if now - t0 >= 1.0:
            stats["cam_fps"] = round(n / (now - t0), 1)
            n, t0, windows = 0, now, windows + 1
            if windows >= 3 and not reported:
                reported = True
                h, w = frame.shape[:2]
                print(f"[camera] {w}x{h} at {stats['cam_fps']} fps")
                if stats["cam_fps"] < 20 and not is_file:
                    print("[camera] under 20 fps. Room is probably dim: press a Shutter button on the "
                          "test page (-5 or -6) or add light. Or run with --width 640 --height 480.")

        if is_file:                           # play test files at their real speed
            next_file_t += file_gap
            delay = next_file_t - time.time()
            if delay > 0:
                time.sleep(delay)
            else:
                next_file_t = time.time()
    cap.release()


# ------------------------------------------------------------ live stream
def encoder_loop(args):
    """Thread 2: turn the NEWEST camera frame into the live-view JPEG."""
    last_seq, last_emit = -1, 0.0
    n, t0 = 0, time.time()

    while not shutdown:
        seq, item = raw_box.wait_newer(last_seq, 0.5)
        if item is None or seq == last_seq:
            continue
        last_seq = seq
        frame, _ = item
        now = time.time()
        h, w = frame.shape[:2]
        scale = min(1.0, tune["max"] / max(w, h))
        sw, sh = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)

        if now - t0 >= 1.0:
            stats["enc_fps"] = round(n / (now - t0), 1)
            n, t0 = 0, now

        if now - last_emit < 1.0 / max(1.0, tune["fps"]) - 0.008:
            continue                          # rate limit: skip this frame
        last_emit = now

        tp = time.perf_counter()
        view = cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA) if scale < 1.0 else frame.copy()
        s = sw / 540.0
        if active:
            t = max(0.0, now - mission_start)
            cv2.circle(view, (int(24 * s), int(24 * s)), max(3, int(9 * s)), (0, 0, 255), -1)
            cv2.putText(view, f"REC {t:5.1f}s", (int(42 * s), int(32 * s)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7 * s, (0, 0, 255), max(1, int(2 * s)), cv2.LINE_AA)
        if active and now < overlay_until:
            cv2.putText(view, overlay_text, (int(16 * s), int(74 * s)), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0 * s, (0, 0, 255), max(1, int(2 * s)), cv2.LINE_AA)
        ok, jpg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, int(tune["q"])])
        if ok:
            jpeg_box.put(jpg.tobytes())
            n += 1
        ms = (time.perf_counter() - tp) * 1000
        stats["enc_ms"] = round(0.9 * stats["enc_ms"] + 0.1 * ms, 1) if stats["enc_ms"] else round(ms, 1)


# ------------------------------------------------------------ recorder
def recorder_loop(args):
    """Thread 3: save full-quality video + sharp keyframes. Never blocks the live view."""
    global active, mission_no, mission_dir, mission_start, frame_idx, keyframe_idx, events

    st = {"writer": None, "kf_log": None, "kf_writer": None, "best": None, "next_kf": 0.0,
          "n": 0, "t0": time.time()}

    def begin():
        global active, mission_no, mission_dir, mission_start, frame_idx, keyframe_idx, events
        while True:                            # throw away anything left from before
            try:
                rec_q.get_nowait()
            except queue.Empty:
                break
        with lock:
            mission_no += 1
            mission_dir = out_root / datetime.now().strftime("mission_%Y%m%d_%H%M%S")
            (mission_dir / "frames").mkdir(parents=True, exist_ok=True)
            with open(mission_dir / "events.csv", "w", newline="") as f:
                csv.writer(f).writerow(["t_seconds", "frame", "keyframe", "label", "source", "clock"])
            mission_start, frame_idx, keyframe_idx, events = time.time(), 0, 0, []
            stats["rec_dropped"] = 0
            active = True
        st["kf_log"] = open(mission_dir / "keyframes.csv", "w", newline="")
        st["kf_writer"] = csv.writer(st["kf_log"])
        st["kf_writer"].writerow(["keyframe", "file", "t_seconds", "sharpness"])
        st["best"], st["next_kf"] = None, args.keyframe_every
        print(f"[mission] started -> {mission_dir}")

    def save_keyframe():
        global keyframe_idx
        frame, score, t = st["best"]
        name = f"kf_{keyframe_idx:05d}.jpg"
        cv2.imwrite(str(mission_dir / "frames" / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        st["kf_writer"].writerow([keyframe_idx, name, round(t, 2), round(score, 1)])
        st["kf_log"].flush()
        st["best"] = None
        with lock:
            keyframe_idx += 1

    def handle(frame, t_cap):
        global frame_idx
        tp = time.perf_counter()
        h, w = frame.shape[:2]
        if st["writer"] is None:              # write at the rate the camera really delivers
            fps = stats["cam_fps"] if stats["cam_fps"] >= 5 else args.cam_fps
            if fps > 45:
                fps /= 2                      # 60 fps camera: we record every 2nd frame
            st["writer"] = cv2.VideoWriter(str(mission_dir / "video.mp4"),
                                           cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        st["writer"].write(frame)             # saved video has no text on it

        t = max(0.0, t_cap - mission_start)
        small = cv2.resize(frame, (320, max(1, int(320 * h / w))))
        score = cv2.Laplacian(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        if st["best"] is None or score > st["best"][1]:
            st["best"] = (frame, score, t)    # keep only the sharpest frame in each window
        if t >= st["next_kf"]:
            st["next_kf"] += args.keyframe_every
            save_keyframe()
        with lock:
            frame_idx += 1

        st["n"] += 1
        ms = (time.perf_counter() - tp) * 1000
        stats["rec_ms"] = round(0.9 * stats["rec_ms"] + 0.1 * ms, 1) if stats["rec_ms"] else round(ms, 1)

    def end():
        global active
        with lock:
            active = False                    # capture thread stops feeding the queue
        while True:                           # write whatever is still waiting
            try:
                no, frame, t_cap = rec_q.get_nowait()
            except queue.Empty:
                break
            if no == mission_no:
                handle(frame, t_cap)
        if st["writer"] is not None:
            st["writer"].release()
            st["writer"] = None
        if st["kf_log"] is not None:
            st["kf_log"].close()
            st["kf_log"] = None
        dropped = stats["rec_dropped"]
        print(f"[saved] {mission_dir.resolve()}  ({keyframe_idx} keyframes, {len(events)} events"
              f"{', ' + str(dropped) + ' frames dropped' if dropped else ''})")

    while not shutdown:
        if want_active and not active:
            begin()
        elif not want_active and active:
            end()
        now = time.time()
        if now - st["t0"] >= 1.0:
            stats["rec_fps"] = round(st["n"] / (now - st["t0"]), 1) if active else 0.0
            st["n"], st["t0"] = 0, now
        try:
            no, frame, t_cap = rec_q.get(timeout=0.05)
        except queue.Empty:
            continue
        if active and no == mission_no:
            handle(frame, t_cap)
    if active:
        end()


# ------------------------------------------------------------ arduino
def find_arduino():
    for p in list_ports.comports():
        text = f"{p.description} {p.manufacturer}".lower()
        if (p.vid == 0x2341 or
                any(k in text for k in ("arduino", "ch340", "cp210", "usb serial", "usb-serial"))):
            return p.device
    return None


def handle_serial_line(line):
    """One line of text from the Arduino."""
    global last_hb, pins, last_tap1
    if line == "TAP1":
        now = time.time()
        if now - last_tap1 < tap_lockout:     # one touch sometimes fires twice
            print("[arduino] extra tap ignored (too soon after the last one)")
            return
        last_tap1 = now
        toggle("arduino")
    elif line == "TAP2":
        add_event("hazard", "arduino")
    elif line.startswith("HB"):               # heartbeat: "HB <d2> <d3> ..." (1 = pressed; v3 adds more fields)
        try:
            vals = [int(x) for x in line.split()[1:3]]
        except ValueError:
            return
        with lock:
            last_hb = time.time()
            if len(vals) == 2:
                pins = vals
    elif line.startswith("READY"):
        print(f"[arduino] sketch started ({line})")
    elif line.startswith("INFO"):             # v3 sketch reports what each pin rests at
        print(f"[arduino] {line[4:].strip()}")
    elif line:
        print(f"[arduino] unexpected text from board: {line!r}  "
              f"(old or wrong sketch on the board, or baud rate is not 9600)")


def serial_loop(port):
    global arduino_ok
    while not shutdown:
        try:
            with serial.Serial(port, 9600, timeout=1, write_timeout=1) as ser:
                arduino_ok = True
                opened, warned, asked = time.time(), False, False
                print(f"[arduino] connected on {port}")
                while not shutdown:
                    if not asked and time.time() - opened > 0.5:
                        asked = True
                        try:
                            ser.write(b"L")   # v3 sketch: learn what the sensors rest at, right now
                        except serial.SerialException:
                            pass              # older sketch, not listening. Harmless.
                    line = ser.readline().decode(errors="ignore").strip()
                    handle_serial_line(line)
                    if not warned and last_hb < opened and time.time() - opened > 5:
                        warned = True
                        print("[arduino] port is open but the board is SILENT. The v3 "
                              "tap_buttons.ino is not running on it. Stop this script "
                              "(Ctrl+C), upload the sketch, then start this again.")
        except Exception as e:
            arduino_ok = False
            print(f"[arduino] {e}. Retrying in 2s...")
            time.sleep(2)


# ------------------------------------------------------------ web
PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Tap stream test (__VERSION__)</title><style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:16px;text-align:center}
h2 small{font-weight:400;color:#888;font-size:14px}
#v{max-width:100%;max-height:80vh;border-radius:8px;background:#000}
button{font-size:15px;padding:9px 16px;margin:4px;border:0;border-radius:6px;cursor:pointer;color:#fff;background:#3a3a3a}
button.big{font-size:17px;padding:11px 20px}
button.sel{background:#2e7d32}
.mono{font-family:monospace;margin:6px;font-size:14px}
#p{color:#9ad}
#a b{padding:2px 8px;border-radius:4px;background:#333}#a b.on{background:#2e7d32}
.row{margin:10px auto;max-width:640px;padding:8px;border:1px solid #2a2a2a;border-radius:8px}
.row .t{font-size:13px;color:#aaa;margin-bottom:4px}
#log{text-align:left;max-width:520px;margin:10px auto;font-family:monospace;font-size:14px}
</style></head><body>
<h2>Tap stream test page <small>__VERSION__</small></h2>
<img id=v src="/stream">
<div id=s class=mono></div><div id=p class=mono></div><div id=a class=mono></div>
<div>
<button class=big style="background:#1565c0" onclick="fetch('/toggle')">Start / Stop</button>
<button class=big style="background:#c62828" onclick="fetch('/mark?label=hazard')">Mark hazard</button>
</div>
<div class=row><div class=t>SHUTTER &nbsp; picture smears or warps when you move? pick a lower number (sharper, but darker)</div>
<span id=exp></span></div>
<div class=row><div class=t>BRIGHTNESS BOOST (gain), only used when the shutter is locked</div>
<input id=gain type=range min=0 max=255 value=64 style="width:60%" onchange="fetch('/camera?gain='+this.value)">
<span id=gv class=mono></span></div>
<div class=row><div class=t>STREAM QUALITY &nbsp; (saved video and keyframes are always full quality)</div>
<span id=pre></span>
</div>
<div class=row><div class=t>CAMERA &nbsp; (everything is automatic by default, same as the Windows Camera app)</div>
<button data-f="auto" onclick="fetch('/camera?focus=auto')">Autofocus</button>
<button data-f="locked" onclick="fetch('/camera?focus=lock')">Lock focus here</button>
<button onclick="fetch('/camera?settings=1')">Open camera settings window</button></div>
<div id=log></div>
<script>
const $=id=>document.getElementById(id);
const EXPS=['auto',-4,-5,-6,-7,-8];
const PRES=['light','balanced','sharp','ultra'];
$('exp').innerHTML=EXPS.map(e=>'<button data-e="'+e+'" onclick="fetch(\\'/camera?exposure='+e+'\\')">'+(e==='auto'?'Auto':e)+'</button>').join('');
$('pre').innerHTML=PRES.map(p=>'<button data-p="'+p+'" onclick="fetch(\\'/tune?preset='+p+'\\')">'+p[0].toUpperCase()+p.slice(1)+'</button>').join('');
let boot=null,down=false;
const pin=(n,x)=>'<b class="'+(x===1?'on':'')+'">'+n+'='+(x===null?'?':x)+'</b>';
async function tick(){
 let s;
 try{s=await(await fetch('/status')).json()}
 catch(e){down=true;$('s').textContent='backpack script is not running';return}
 if(boot&&boot!==s.boot){location.reload();return}
 if(down){$('v').src='/stream?'+Date.now()}
 boot=s.boot;down=false;
 $('s').textContent=s.active?('RECORDING  '+s.elapsed+'s   keyframes '+s.keyframes):'LIVE  not recording';
 $('p').textContent='camera '+s.cam_fps+' fps ('+s.cam_mode+')   stream '+s.enc_fps+' fps made, '+s.sent_fps+' sent'
   +(s.active?'   recording '+s.rec_fps+' fps'+(s.rec_dropped?' ('+s.rec_dropped+' dropped)':''):'')
   +'   encode '+s.enc_ms+' ms';
 $('a').innerHTML=!s.arduino?'arduino: NOT CONNECTED (port busy or unplugged)':
  !s.sketch?'arduino: connected but SILENT - upload tap_buttons.ino (v3)':
  'arduino: OK &nbsp; '+pin('D2',s.pins[0])+' '+pin('D3',s.pins[1]);
 document.querySelectorAll('[data-e]').forEach(b=>b.classList.toggle('sel',String(s.exposure)===b.dataset.e));
 document.querySelectorAll('[data-p]').forEach(b=>b.classList.toggle('sel',s.preset===b.dataset.p));
 document.querySelectorAll('[data-f]').forEach(b=>b.classList.toggle('sel',s.focus===b.dataset.f));
 $('gv').textContent=s.gain===null?'':'gain '+s.gain;
 try{const e=await(await fetch('/events')).json();
 $('log').innerHTML=e.slice(-8).reverse().map(x=>x.clock+'  <b>'+x.label+'</b>  t='+x.t+'s  keyframe '+x.keyframe).join('<br>')}catch(e){}
}
setInterval(tick,500);tick();
</script></body></html>""".replace("__VERSION__", VERSION)


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/")
def index():
    resp = Response(PAGE, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _tune_socket():
    """Small send buffer + no Nagle delay, so a slow viewer skips frames instead of lagging."""
    sock = request.environ.get("werkzeug.socket")
    if sock is None:
        return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
    except OSError:
        pass


@app.route("/stream")
def stream():
    _tune_socket()

    def gen():
        last_seq, n, t0 = -1, 0, time.time()
        stats["clients"] += 1
        try:
            while not shutdown:
                seq, jpg = jpeg_box.wait_newer(last_seq, 1.0)
                if jpg is None or seq == last_seq:
                    continue
                last_seq = seq                # always the newest frame, never a backlog
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                n += 1
                now = time.time()
                if now - t0 >= 1.0:
                    stats["sent_fps"] = round(n / (now - t0), 1)
                    n, t0 = 0, now
        finally:
            stats["clients"] -= 1

    resp = Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/frame.jpg")
def frame_jpg():
    jpg = jpeg_box.item
    if jpg is None or time.time() - jpeg_box.updated_at > 2:
        return ("camera frame unavailable", 503)
    resp = Response(jpg, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def current_preset():
    for name, p in PRESETS.items():
        if all(tune[k] == p[k] for k in p):
            return name
    return "custom"


@app.route("/status")
def status():
    with lock:
        out = {
            "version": VERSION,
            "boot": boot_id,
            "active": active,
            "mission": mission_dir.name if mission_dir else None,
            "elapsed": round(time.time() - mission_start, 1) if active else 0,
            "frames": frame_idx,
            "keyframes": keyframe_idx,
            "arduino": arduino_ok,
            "sketch": arduino_ok and (time.time() - last_hb) < 2.0,
            "pins": pins,
            "exposure": cam_state["exposure"],
            "gain": cam_state["gain"],
            "focus": cam_state["focus"],
            "preset": current_preset(),
            "tune": dict(tune),
        }
    out.update(stats)
    return jsonify(out)


@app.route("/events")
def get_events():
    with lock:
        return jsonify(list(events))


@app.route("/toggle")
def http_toggle():
    toggle("web")
    return jsonify({"want_active": want_active})


@app.route("/start")
def http_start():
    global want_active
    want_active = True
    return "ok"


@app.route("/stop")
def http_stop():
    global want_active
    want_active = False
    return "ok"


@app.route("/mark")
def mark():
    ok = add_event(request.args.get("label", "mark"), "web")
    return ("ok", 200) if ok else ("no mission running", 409)


@app.route("/tune")
def http_tune():
    preset = request.args.get("preset")
    if preset in PRESETS:
        tune.update(PRESETS[preset])
    try:
        if "max" in request.args:
            tune["max"] = min(1920, max(160, int(request.args["max"])))
        if "fps" in request.args:
            tune["fps"] = min(60.0, max(1.0, float(request.args["fps"])))
        if "q" in request.args:
            tune["q"] = min(95, max(30, int(request.args["q"])))
    except ValueError:
        return ("bad number", 400)
    print(f"[stream] {tune['max']}px  {tune['fps']:.0f} fps  quality {tune['q']}")
    return jsonify(tune)


@app.route("/camera")
def http_camera():
    if not cam_state["live"]:
        return ("not a live camera (test file)", 409)
    try:
        if "exposure" in request.args:
            v = request.args["exposure"]
            cam_requests.append(("exposure", None if v == "auto" else float(v)))
        if "gain" in request.args:
            cam_requests.append(("gain", float(request.args["gain"])))
        if request.args.get("focus") in ("auto", "lock"):
            cam_requests.append(("focus", request.args["focus"]))
        if "settings" in request.args:
            cam_requests.append(("settings", 1))
    except ValueError:
        return ("bad number", 400)
    return "ok"


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ------------------------------------------------------------ main
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="1",
                    help="camera number (0 = built-in, 1 = Logitech usually) or a video file for testing")
    ap.add_argument("--rotate", default="none", choices=list(ROTATIONS))
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--backend", default="dshow", choices=["dshow", "msmf"],
                    help="Windows camera system. dshow is the default; msmf is what the Camera app uses.")
    ap.add_argument("--cam-fps", type=float, default=30.0, help="frame rate to ask the camera for")
    ap.add_argument("--keyframe-every", type=float, default=0.5)
    ap.add_argument("--exposure", type=float, default=None,
                    help="lock the shutter, e.g. -6. Lower = sharper when moving but darker. Blank = auto.")
    ap.add_argument("--gain", type=float, default=None, help="brightness boost 0-255 when the shutter is locked")
    ap.add_argument("--lock-focus", action="store_true",
                    help="freeze the focus where it is at startup (default: autofocus stays on, like the Camera app)")
    ap.add_argument("--settings", action="store_true", help="open the Windows camera settings window at start")
    ap.add_argument("--preset", default="sharp", choices=list(PRESETS), help="live stream quality")
    ap.add_argument("--tap-lockout", type=float, default=1.0,
                    help="ignore a second start/stop tap within this many seconds")
    ap.add_argument("--out", default=None, help="where recordings go. Default: <home>/vt26_recordings")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to serve on (default: local computer only; use 0.0.0.0 for LAN)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--serial", default=None, help="Arduino port like COM5. Blank = auto-detect.")
    args = ap.parse_args()

    tune.update(PRESETS[args.preset])
    tap_lockout = args.tap_lockout
    out_root = Path(args.out) if args.out else Path.home() / "vt26_recordings"
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"tap_stream {VERSION}")
    print(f"Recordings folder: {out_root}")

    threads = [threading.Thread(target=f, args=(args,), daemon=True)
               for f in (capture_loop, encoder_loop, recorder_loop)]
    for t in threads:
        t.start()

    if serial is None:
        print("[arduino] pyserial not installed. Use the web buttons instead.")
    else:
        port = args.serial or find_arduino()
        if port:
            threading.Thread(target=serial_loop, args=(port,), daemon=True).start()
        else:
            print("[arduino] not found. Use the web buttons, or pass --serial COM5")

    logging.getLogger("werkzeug").setLevel(logging.ERROR)   # no request spam in the terminal
    print(f"Test page (this laptop):   http://localhost:{args.port}")
    if args.host == "0.0.0.0":
        print(f"For teammates (same wifi): http://{lan_ip()}:{args.port}/stream")
    print("Press Ctrl+C to quit")
    try:
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        shutdown = True
        threads[2].join(timeout=8)            # let the recorder finish the video file
