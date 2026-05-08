import logging
import os
import signal
import time
import threading
import uuid
import wave
from logging.handlers import RotatingFileHandler
from pathlib import Path

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSPasteboard
from Quartz import (
    CGEventTapCreate, CGEventTapEnable,
    CGEventGetIntegerValueField, CGEventGetFlags,
    CGEventCreateKeyboardEvent, CGEventSetFlags, CGEventPost,
    CGEventMaskBit, CFMachPortCreateRunLoopSource,
    kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionListenOnly,
    kCGEventFlagsChanged, kCGKeyboardEventKeycode,
    kCGEventFlagMaskCommand, kCGHIDEventTap,
    kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput,
)
from CoreFoundation import (
    CFRunLoopAddSource, CFRunLoopGetCurrent, CFRunLoopRun, kCFRunLoopDefaultMode,
)
from PyObjCTools import AppHelper

from recorder import Recorder
from transcriber import Transcriber, TranscriptionError, write_wav, GROQ_API_KEYS
from overlay import Overlay

# Hotkey configuration. Default is right Command.
# To use a different modifier, change both constants — see README for keycode/flag table.
HOTKEY_KEYCODE = 0x36   # right Command
HOTKEY_FLAG    = 0x10   # NX_DEVICERCMDKEYMASK — distinguishes right Cmd from left
V_KEY = 0x09
MIN_AUDIO_SAMPLES = 16000
PB_TYPE = "public.utf8-plain-text"
PENDING_DIR = Path(".pending")
QUARANTINE_DIR = PENDING_DIR / "quarantine"

# Watchdog: an independent poll thread resets stuck states. Triggers when a
# key-up is lost (Secure Input app, tap glitch, mid-recording crash) and the
# state machine would otherwise sit forever with audio buffering in memory.
RECORDING_TIMEOUT_SEC = 300
PROCESSING_TIMEOUT_SEC = 180
WATCHDOG_POLL_SEC = 5

# Long-term observability
PENDING_AGE_WARN_DAYS = 7


# Bounded log file: 2 MB × 3 files = 6 MB max ever on disk
LOG_DIR = Path.home() / "Library/Logs/com.openspeaksy"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_logger = logging.getLogger("openspeaksy")
_logger.setLevel(logging.INFO)
_logger.propagate = False
_handler = RotatingFileHandler(
    LOG_DIR / "main.log", maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
_logger.addHandler(_handler)


def log(msg):
    _logger.info(msg)


def handle_shutdown(signum, frame):
    log(f"received signal {signum}, exiting")
    os._exit(128 + signum)


recorder = Recorder()
transcriber = Transcriber()
overlay = Overlay()

state = "idle"
state_ts = time.monotonic()
state_lock = threading.Lock()
# Per-job token. Each on_key_up bumps this and the spawned worker captures it.
# A worker may only mutate state/clipboard if its token still matches current_job_id —
# otherwise it is a stale completion from a watchdog-reset cycle.
current_job_id = 0
tap_ref = None
source_ref = None


def set_state(new):
    global state, state_ts
    with state_lock:
        state = new
        state_ts = time.monotonic()


def cas_state(expected, new):
    """Atomic compare-and-set. Returns True if state was updated."""
    global state, state_ts
    with state_lock:
        if state == expected:
            state = new
            state_ts = time.monotonic()
            return True
        return False


def begin_processing():
    """
    Atomically transition recording→processing AND allocate a fresh job_id under
    the same lock. Splitting these into two separate locks would leave a window
    in which an old worker could match the new "processing" state with its
    pre-watchdog-reset token. Returns the new job_id, or None if state wasn't
    "recording" when called.
    """
    global state, state_ts, current_job_id
    with state_lock:
        if state != "recording":
            return None
        state = "processing"
        state_ts = time.monotonic()
        current_job_id += 1
        return current_job_id


def _claim_job_completion(job_id):
    """
    Transition processing→idle ONLY if this specific job is still the current one.
    Prevents a stale worker (whose generation was bumped by a watchdog reset and
    a new recording cycle) from clobbering the active job's state or pasting old
    text into the user's current app.
    """
    global state, state_ts
    with state_lock:
        if state == "processing" and current_job_id == job_id:
            state = "idle"
            state_ts = time.monotonic()
            return True
        return False


def _watchdog_tick():
    """
    Single watchdog pass. State mutation AND resource cleanup happen under
    the same state_lock — releasing the lock between the two creates a
    window in which on_key_down can start a fresh recording that the
    cleanup then clobbers (silent failure for the user).

    recorder.stop() is blocking PortAudio I/O. Holding state_lock during
    it briefly blocks tap-thread callbacks, but the watchdog only fires
    when something has been stuck for minutes already, so the extra
    millisecond of lock contention is invisible.

    overlay.hide() is non-blocking — it just queues onto the AppKit main
    loop via AppHelper.callAfter, so holding the lock during it is free.
    """
    global state, state_ts, current_job_id
    with state_lock:
        elapsed = time.monotonic() - state_ts
        stuck = None
        if state == "recording" and elapsed > RECORDING_TIMEOUT_SEC:
            log(f"watchdog: stuck in recording for {elapsed:.0f}s, resetting")
            state = "idle"
            state_ts = time.monotonic()
            current_job_id += 1  # invalidate any in-flight worker token
            stuck = "recording"
        elif state == "processing" and elapsed > PROCESSING_TIMEOUT_SEC:
            log(f"watchdog: stuck in processing for {elapsed:.0f}s, resetting")
            state = "idle"
            state_ts = time.monotonic()
            current_job_id += 1
            stuck = "processing"

        if stuck == "recording":
            # Drain the in-memory audio buffer; a stuck recording is by
            # definition not a clean dictation worth saving.
            try:
                recorder.stop()
            except Exception as e:
                log(f"watchdog recorder.stop error: {e}")
        if stuck:
            overlay.hide()


def watchdog_loop():
    while True:
        time.sleep(WATCHDOG_POLL_SEC)
        try:
            _watchdog_tick()
        except Exception as e:
            log(f"watchdog loop error: {e}")


def copy_to_clipboard(text):
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, PB_TYPE)


def paste_text(text):
    try:
        copy_to_clipboard(text)
        time.sleep(0.05)

        for press in (True, False):
            e = CGEventCreateKeyboardEvent(None, V_KEY, press)
            CGEventSetFlags(e, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, e)

        return True
    except Exception as e:
        log(f"paste error: {e}")
        return False


def _ensure_pending_dir():
    PENDING_DIR.mkdir(exist_ok=True, mode=0o700)
    try:
        os.chmod(PENDING_DIR, 0o700)
    except OSError as e:
        log(f"chmod pending dir error: {e}")


def save_pending_recording(audio):
    _ensure_pending_dir()
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}.wav"
    final = PENDING_DIR / name
    tmp = PENDING_DIR / (name + ".tmp")
    write_wav(audio, tmp)
    try:
        os.chmod(tmp, 0o600)
    except OSError as e:
        log(f"chmod pending file error: {e}")
    os.replace(tmp, final)  # atomic — recovery never sees a half-written WAV
    return final


def delete_pending_recording(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def quarantine_path(path, reason):
    QUARANTINE_DIR.mkdir(exist_ok=True, mode=0o700)
    target = QUARANTINE_DIR / path.name
    try:
        path.rename(target)
        log(f"quarantined {path.name}: {reason}")
    except OSError as e:
        log(f"quarantine error {path.name}: {e}")


def is_valid_wav(path):
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() > 0
    except Exception:
        return False


def process_pending_recording(path, job_id):
    """
    Live worker spawned by on_key_up. job_id is the generation token captured
    when the worker was scheduled. Recovery uses recover_pending_recordings
    instead — it has different rules around the clipboard.
    """
    text = None
    error = False
    try:
        text = transcriber.transcribe_wav_sync(path)
    except TranscriptionError as e:
        log(f"transcription error {path.name}: {e}")
        error = True
    except Exception as e:
        log(f"processing error {path.name}: {e}")
        error = True

    # Claim ownership of THIS job. cas_state on its own would also accept a
    # newer job's processing state — we need an exact job_id match so a stale
    # worker can't paste old text into whatever the user is doing now.
    if not _claim_job_completion(job_id):
        log(f"stale worker abandoned: {path.name}")
        return

    if error:
        overlay.flash_error()
        return  # keep file for retry

    if text:
        if paste_text(text):
            log(f"pasted {len(text)} chars from {path.name}")
            overlay.hide()
        else:
            overlay.flash_error()
            return  # keep file
    else:
        overlay.hide()

    delete_pending_recording(path)


RECOVERY_SEPARATOR = "\n\n---\n\n"


def recover_pending_recordings():
    """
    Startup recovery. Transcribes every pending WAV, joins them with a separator,
    and writes the combined text to the clipboard once at the end. Per-file
    overwrite would lose all but the last transcript. Never auto-pastes — focus
    at login is unrelated to the dictation context.

    Runs synchronously BEFORE the event tap activates so a fresh dictation
    can never race the recovery clipboard write.
    """
    if not PENDING_DIR.exists():
        return

    # Clean up partial writes from a previous crash mid-save
    for tmp in PENDING_DIR.glob("*.tmp"):
        try:
            tmp.unlink()
            log(f"removed partial write: {tmp.name}")
        except OSError:
            pass

    paths = sorted(PENDING_DIR.glob("*.wav"))
    if not paths:
        return

    cutoff = time.time() - PENDING_AGE_WARN_DAYS * 86400
    stale = sum(1 for p in paths if p.stat().st_mtime < cutoff)
    if stale:
        log(f"WARNING: {stale} pending recording(s) older than {PENDING_AGE_WARN_DAYS}d — Groq API may be unreachable")

    log(f"found {len(paths)} pending recording(s)")
    recovered = []  # (path, text); text may be empty for hallucination/silence
    for path in paths:
        if not is_valid_wav(path):
            quarantine_path(path, "corrupt WAV header")
            continue
        try:
            text = transcriber.transcribe_wav_sync(path)
        except TranscriptionError as e:
            log(f"recovery transcription error {path.name}: {e}")
            continue  # leave file for next startup
        except Exception as e:
            log(f"recovery processing error {path.name}: {e}")
            continue  # leave file for next startup
        recovered.append((path, text))

    non_empty = [(p, t) for p, t in recovered if t]

    if non_empty:
        combined = RECOVERY_SEPARATOR.join(t for _, t in non_empty)
        try:
            copy_to_clipboard(combined)
            log(f"recovered {len(non_empty)} dictation(s) ({len(combined)} chars total) to clipboard")
        except Exception as e:
            log(f"recovery clipboard error: {e}")
            return  # leave all files in pending so a future startup can retry

    # Delete files only after a successful clipboard write (or on filtered-empty results)
    for path, _ in recovered:
        delete_pending_recording(path)


def on_key_down():
    if not cas_state("idle", "recording"):
        return
    try:
        recorder.start()
        overlay.show("recording")
    except Exception as e:
        log(f"recorder.start error: {e}")
        overlay.hide()
        set_state("idle")


def on_key_up():
    # Atomically claim the recording→processing transition AND a fresh job_id.
    # An old worker's claim must not match this id even in the tiny window
    # between state change and worker spawn.
    job_id = begin_processing()
    if job_id is None:
        return

    try:
        audio = recorder.stop()
    except Exception as e:
        log(f"recorder.stop error: {e}")
        overlay.hide()
        set_state("idle")
        return

    if len(audio) < MIN_AUDIO_SAMPLES:
        overlay.hide()
        set_state("idle")
        return

    try:
        wav_path = save_pending_recording(audio)
    except Exception as e:
        log(f"save pending recording error: {e}")
        overlay.hide()
        set_state("idle")
        return

    overlay.show("loading")
    threading.Thread(target=process_pending_recording, args=(wav_path, job_id), daemon=True).start()


def tap_callback(proxy, event_type, event, refcon):
    # Wrap entire body — Python exceptions from here propagate into the
    # CGEventTap C callback and can take down the run loop
    try:
        if event_type == kCGEventTapDisabledByTimeout or event_type == kCGEventTapDisabledByUserInput:
            CGEventTapEnable(tap_ref, True)
            log(f"event tap re-enabled (reason: {event_type})")
            return event

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if keycode == HOTKEY_KEYCODE:
            # Device-dependent flag distinguishes left vs right modifier —
            # the shared mask (e.g. kCGEventFlagMaskCommand) catches both
            pressed = bool(CGEventGetFlags(event) & HOTKEY_FLAG)
            if pressed:
                on_key_down()
            else:
                on_key_up()
    except Exception as e:
        log(f"tap_callback error: {e}")

    return event


def run_event_tap():
    global tap_ref, source_ref

    tap_ref = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        CGEventMaskBit(kCGEventFlagsChanged),
        tap_callback,
        None,
    )
    if tap_ref is None:
        log("Failed to create event tap")
        log("Grant Input Monitoring: System Settings > Privacy & Security > Input Monitoring")
        os._exit(1)

    source_ref = CFMachPortCreateRunLoopSource(None, tap_ref, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source_ref, kCFRunLoopDefaultMode)
    CGEventTapEnable(tap_ref, True)
    log("event tap active")
    CFRunLoopRun()


def main():
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    if not GROQ_API_KEYS:
        log(
            "FATAL: no Groq API key configured. Set GROQ_API_KEYS in "
            "~/Library/LaunchAgents/com.openspeaksy.plist (EnvironmentVariables) "
            "and reload. Get a free key at https://console.groq.com/keys."
        )
        os._exit(1)

    log(f"OpenSpeaksy starting — backend: Groq cloud ({len(GROQ_API_KEYS)} key(s)), audio leaves the Mac")

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # Recovery runs synchronously BEFORE the tap activates so a fresh dictation
    # cannot race the recovery clipboard write.
    recover_pending_recordings()

    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=run_event_tap, daemon=True).start()
    time.sleep(0.1)

    log("OpenSpeaksy running — hold right Command to record")
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
