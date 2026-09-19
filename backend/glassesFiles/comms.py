"""
comms.py  -  automatic voice comms for the wearable rig (ElevenLabs voice).

    import comms
    comms.say("Teammate two found a person on floor two")

The voice comes out of whatever speaker Windows is using as its DEFAULT OUTPUT.
So the same code works for every speaker in the plan:
    testing on the desk  -> pair the Google Home Mini to the laptop over Bluetooth
    on the wearer        -> pair the glasses (or earbuds) over Bluetooth instead
Switch speakers in Windows (click the volume icon, pick the output). No code change.

SETUP (once)
    1. Get an API key from elevenlabs.io (Developers / API Keys).
    2. In PowerShell:   setx ELEVENLABS_API_KEY "paste-your-key-here"
       then CLOSE and reopen PowerShell.
       NEVER put the key in a file inside the git repo. The repo is public.
    3. Test it:         python comms.py "Comms check. Foundry is online."

No extra pip installs. If there is no key or no internet it falls back to the
built-in Windows voice, so the demo never goes silent.

Tuning (optional environment variables):
    ELEVENLABS_VOICE_ID   default JBFqnCBsd6RMkjVDRZzb  (George)
    ELEVENLABS_MODEL_ID   default eleven_flash_v2_5     (the low-latency model)
    COMMS_LEAD_IN         default 1.2   seconds of silence played before a message
                          when the speaker has been quiet for a while. Bluetooth
                          speakers fall asleep and swallow the first second or two
                          of sound; this wakes them up first. Set to 0 for wired or
                          laptop speakers.
"""

import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

try:
    import winsound                      # Windows only, built in
except ImportError:
    winsound = None

VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
SAMPLE_RATE = 24000                      # pcm_24000 works on every ElevenLabs plan
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_{rate}"
CACHE_DIR = Path.home() / ".vt26_voice_cache"
MAX_CHARS = 300                          # comms should be short
MAX_WAITING = 4                          # stale comms are worse than no comms
LEAD_IN = float(os.environ.get("COMMS_LEAD_IN", "1.2"))   # seconds, see the notes above
AWAKE_FOR = 4.0                          # a Bluetooth speaker stays awake about this long
_last_sound_end = 0.0

_q = queue.Queue()
_lock = threading.Lock()
_recent = {}                             # text -> last time it was queued
_state = {"engine": "not started", "last_said": None, "last_error": None, "spoken": 0}
_worker = None


def _api_key():
    return os.environ.get("ELEVENLABS_API_KEY", "").strip()


def _pcm_to_wav(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)                # 16-bit
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def synthesize(text):
    """Text -> WAV bytes from ElevenLabs. Cached on disk, so a repeated phrase is
    instant, costs no credits, and still works if the wifi drops."""
    key = _api_key()
    name = hashlib.sha1(f"{VOICE_ID}|{MODEL_ID}|{text}".encode()).hexdigest() + ".wav"
    path = CACHE_DIR / name
    if path.exists():
        return path.read_bytes()
    if not key:
        raise RuntimeError("no ELEVENLABS_API_KEY set")

    req = urllib.request.Request(
        API_URL.format(voice=VOICE_ID, rate=SAMPLE_RATE),
        data=json.dumps({"text": text, "model_id": MODEL_ID}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            pcm = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode(errors="ignore")
        raise RuntimeError(f"ElevenLabs said {e.code}: {detail}") from None
    if len(pcm) < 1000:
        raise RuntimeError("ElevenLabs returned no audio")

    wav = _pcm_to_wav(pcm)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav)
    except OSError:
        pass
    return wav


def _pad_wav(wav, lead_seconds, tail_seconds=0.25):
    """Put silence in front of (and a little behind) a WAV so a sleeping Bluetooth
    speaker is awake before the first word and does not cut off the last one."""
    with wave.open(io.BytesIO(wav), "rb") as r:
        params, frames = r.getparams(), r.readframes(r.getnframes())
    frame_bytes = params.sampwidth * params.nchannels
    lead = b"\x00" * (int(params.framerate * lead_seconds) * frame_bytes)
    tail = b"\x00" * (int(params.framerate * tail_seconds) * frame_bytes)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(lead + frames + tail)
    return buf.getvalue()


def _play_wav(wav):
    global _last_sound_end
    asleep = time.time() - _last_sound_end > AWAKE_FOR
    wav = _pad_wav(wav, LEAD_IN if asleep else 0.05)
    if winsound is not None:
        winsound.PlaySound(wav, winsound.SND_MEMORY)      # blocks until finished
    else:                                                  # not Windows: dev machine
        print(f"[comms] (no audio on this OS) would play {len(wav)} bytes")
    _last_sound_end = time.time()


def _windows_voice(text):
    """Backup voice built into Windows. Text goes through an environment variable,
    never into the command line, so odd characters cannot break anything."""
    if os.name != "nt":
        print(f"[comms] (backup voice) {text}")
        return
    env = dict(os.environ, VT_SAY=text)
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Add-Type -AssemblyName System.Speech; "
         "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:VT_SAY)"],
        env=env, timeout=30, capture_output=True,
    )


def _speak_now(text):
    try:
        wav = synthesize(text)
        _state["engine"] = "elevenlabs"
        _play_wav(wav)
    except Exception as e:
        if _state["last_error"] != str(e):
            print(f"[comms] ElevenLabs not used ({e}). Using the Windows voice.")
        _state["last_error"] = str(e)
        _state["engine"] = "windows voice (backup)"
        try:
            _windows_voice(text)
        except Exception as e2:
            _state["engine"] = "silent"
            print(f"[comms] no voice available: {e2}")
    _state["last_said"] = text
    _state["spoken"] += 1
    print(f"[comms] said: {text}")


def _run():
    while True:
        text = _q.get()
        if text is None:
            return
        _speak_now(text)


def _ensure_worker():
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, daemon=True)
            _worker.start()


def say(text, dedupe_seconds=8.0):
    """Queue a message. Returns False if it was dropped (empty, or the same
    message was just said). Never blocks the caller."""
    text = " ".join(str(text).split())[:MAX_CHARS]
    if not text:
        return False
    now = time.time()
    with _lock:
        if now - _recent.get(text, 0) < dedupe_seconds:
            return False
        _recent[text] = now
        for k in [k for k, t in _recent.items() if now - t > 60]:
            del _recent[k]
    while _q.qsize() >= MAX_WAITING:     # drop the oldest waiting message
        try:
            dropped = _q.get_nowait()
            print(f"[comms] dropped stale message: {dropped}")
        except queue.Empty:
            break
    _q.put(text)
    _ensure_worker()
    return True


def prewarm(phrases):
    """Generate common phrases in the background at startup so they play instantly."""
    def work():
        for p in phrases:
            try:
                synthesize(p)
            except Exception:
                return
    threading.Thread(target=work, daemon=True).start()


def wait_until_quiet(timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout and (_q.qsize() or _state["last_said"] is None):
        time.sleep(0.1)
    time.sleep(0.2)


def status():
    return {"engine": _state["engine"], "has_key": bool(_api_key()), "waiting": _q.qsize(),
            "last_said": _state["last_said"], "last_error": _state["last_error"]}


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "Comms check. Foundry is online."
    print("key found" if _api_key() else "NO ELEVENLABS_API_KEY found, will use the Windows voice")
    _speak_now(msg)
    print(f"engine used: {_state['engine']}")
