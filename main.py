import fcntl
import logging
import os
import re
import signal
import time
import threading
import uuid
import wave
from logging.handlers import RotatingFileHandler
from pathlib import Path

import objc
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSPasteboard
from Foundation import NSBundle
from Quartz import (
    CGEventTapCreate, CGEventTapEnable,
    CGEventGetIntegerValueField, CGEventGetFlags,
    CGEventCreateKeyboardEvent, CGEventSetFlags, CGEventPost,
    CGPreflightListenEventAccess, CGPreflightPostEventAccess,
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
from transcriber import (
    CORRECT_DICTATION,
    DICTATE_LANGUAGE,
    GEMINI_API_KEYS,
    GEMINI_MODEL,
    GEMINI_REQUESTS_PER_WINDOW,
    MISTRAL_API_KEY,
    MISTRAL_CORRECTION_MODEL,
    MISTRAL_MODEL,
    MISTRAL_TRANSLATION_MODEL,
    POLISH_STT_BACKEND,
    STT_BACKEND,
    SUPPORTED_STT_BACKENDS,
    Transcriber,
    TranscriptionError,
    ProviderUnavailableError,
    write_wav,
)
from overlay import Overlay

# Hotkey configuration. Default is right Command.
# To use a different modifier, change both constants — see README for keycode/flag table.
HOTKEY_KEYCODE   = 0x36   # right Command
HOTKEY_FLAG      = 0x10   # NX_DEVICERCMDKEYMASK — distinguishes right Cmd from left
TRANSLATE_KEYCODE = 0x3D  # right Option — dictate Russian, paste English
TRANSLATE_FLAG    = 0x40  # NX_DEVICERALTKEYMASK
POLISH_KEYCODE = 0x3C   # right Shift — dictate Russian, paste Polish
POLISH_FLAG    = 0x04   # NX_DEVICERSHIFTKEYMASK — distinguishes right Shift from left
MODE_DICTATE   = "dictate"
MODE_TRANSLATE = "translate"
MODE_POLISH    = "polish"
# Overlay label per mode; dictate has none.
MODE_LABELS = {MODE_TRANSLATE: "English", MODE_POLISH: "Polish"}
V_KEY = 0x09
# Ignore accidental taps shorter than 0.8 seconds.
MIN_AUDIO_SAMPLES = 12800
PB_TYPE = "public.utf8-plain-text"
PROJECT_ROOT = Path(__file__).resolve().parent
PENDING_DIR = PROJECT_ROOT / ".pending"
QUARANTINE_DIR = PENDING_DIR / "quarantine"

# Watchdog: an independent poll thread resets stuck states. Triggers when a
# key-up is lost (Secure Input app, tap glitch, mid-recording crash) and the
# state machine would otherwise sit forever with audio buffering in memory.
# The hard limit is only a final memory guard. Reaching it finalizes and
# preserves the audio instead of discarding it. Do not poll
# CGEventSourceKeyState for modifier ownership here: macOS can report a held
# right-side modifier as released, which would cut off valid dictation.
RECORDING_TIMEOUT_SEC = 3600
# Translation makes two provider calls (STT, translate), each with bounded
# retries, and STT may walk several Gemini keys. Keep the watchdog above that
# legitimate retry budget so it never invalidates a worker still making progress.
PROCESSING_TIMEOUT_SEC = 360
WATCHDOG_POLL_SEC = 5

# Long-term observability
PENDING_AGE_WARN_DAYS = 7


# Bounded log file: 2 MB × 3 files = 6 MB max ever on disk
LOG_DIR = Path.home() / "Library/Logs/com.openspeaksy"
FALLBACK_PENDING_DIR = (
    Path.home() / "Library/Application Support/OpenSpeaksy/pending"
)
INSTANCE_LOCK_PATH = LOG_DIR / "instance.lock"
_logger = logging.getLogger("openspeaksy")
_logger.setLevel(logging.INFO)
_logger.propagate = False
_instance_lock_file = None

MICROPHONE_AUTH_NOT_DETERMINED = 0
MICROPHONE_AUTH_RESTRICTED = 1
MICROPHONE_AUTH_DENIED = 2
MICROPHONE_AUTH_AUTHORIZED = 3
MICROPHONE_MEDIA_TYPE = "soun"


def _install_file_handler():
    """
    Attach the rotating file handler. Called from main() — NOT at import —
    so that pytest (which imports main for state-machine tests) can't
    pollute the live agent's log file via the same handler.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(LOG_DIR, 0o700)
    log_path = LOG_DIR / "main.log"
    handler = RotatingFileHandler(
        log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    os.chmod(log_path, 0o600)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(handler)


def log(msg):
    _logger.info(msg)


def _open_instance_lock(lock_path):
    """
    Return an exclusively locked file handle, or None if another OpenSpeaksy
    process already owns the lock. The caller must keep the handle alive for
    the lifetime of the process.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(lock_path.parent, 0o700)
    lock_file = lock_path.open("a+", encoding="ascii")
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None

    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


def _acquire_instance_lock():
    global _instance_lock_file
    _instance_lock_file = _open_instance_lock(INSTANCE_LOCK_PATH)
    return _instance_lock_file is not None


def microphone_authorization_status():
    """
    Query macOS microphone authorization without adding the large
    pyobjc-framework-AVFoundation package. AVFoundation is part of macOS and
    can be loaded through the Objective-C runtime already used by the app.
    Returns None if the status cannot be queried.
    """
    try:
        bundle = NSBundle.bundleWithPath_(
            "/System/Library/Frameworks/AVFoundation.framework"
        )
        if bundle is None or not bundle.load():
            return None
        capture_device = objc.lookUpClass("AVCaptureDevice")
        return int(
            capture_device.authorizationStatusForMediaType_(
                MICROPHONE_MEDIA_TYPE
            )
        )
    except Exception as e:
        log(f"microphone authorization preflight unavailable: {e}")
        return None


def _microphone_access_is_blocked():
    status = microphone_authorization_status()
    return status in {
        MICROPHONE_AUTH_RESTRICTED,
        MICROPHONE_AUTH_DENIED,
    }


def handle_shutdown(signum, _frame):
    global state, state_ts, current_job_id, current_hotkey, current_mode

    with state_lock:
        was_recording = state == "recording"
        mode = current_mode or MODE_DICTATE
        state = "idle"
        state_ts = time.monotonic()
        current_job_id += 1
        current_hotkey = None
        current_mode = None

    if was_recording:
        try:
            audio = recorder.stop()
            if len(audio) >= MIN_AUDIO_SAMPLES:
                path = save_recording_with_fallback(audio, mode)
                log(f"shutdown preserved recording: {path.name}")
        except Exception as e:
            log(f"shutdown recording preservation error: {e}")

    log(f"received signal {signum}, exiting")
    os._exit(128 + signum)


recorder = Recorder()
transcriber = Transcriber()
overlay = Overlay()

state = "idle"
state_ts = time.monotonic()
state_lock = threading.Lock()
# Serializes clipboard mutations between live-worker pastes and the
# background pending-recovery pass, so recovered text can never race a fresh
# dictation paste into the same clipboard.
_clipboard_gate = threading.Lock()
# Per-job token. Each on_key_up bumps this and the spawned worker captures it.
# A worker may only mutate state/clipboard if its token still matches current_job_id —
# otherwise it is a stale completion from a watchdog-reset cycle.
current_job_id = 0
# Which hotkey owns the in-flight cycle. Set in on_key_down, consumed in on_key_up.
# A key-up event whose keycode doesn't match current_hotkey is ignored, so tapping
# the OTHER hotkey mid-record can't end the cycle. Watchdog also clears it on reset.
current_hotkey = None
current_mode = None
# Pending WAV owned by the in-flight processing job. Set in on_key_up before
# the worker spawns; used only for watchdog log messages. Cleared when the
# job is claimed complete or a new cycle begins.
current_wav_path = None
tap_ref = None
source_ref = None
SHUTDOWN_SIGNALS = {signal.SIGTERM, signal.SIGINT}
shutdown_read_fd = None
shutdown_write_fd = None


def begin_processing():
    """
    Atomically transition recording→processing AND allocate a fresh job_id under
    the same lock. Splitting these into two separate locks would leave a window
    in which an old worker could match the new "processing" state with its
    pre-watchdog-reset token. Also captures the cycle's mode under the same
    lock so the worker can route to dictate vs translate without re-reading
    mutable globals.
    Returns (job_id, mode), or (None, None) if state wasn't "recording".
    """
    global state, state_ts, current_job_id, current_hotkey, current_mode
    with state_lock:
        if state != "recording":
            return None, None
        state = "processing"
        state_ts = time.monotonic()
        current_job_id += 1
        mode = current_mode
        current_hotkey = None
        current_mode = None
        return current_job_id, mode


def shutdown_signal_loop():
    """
    Read signal numbers from Python's wakeup fd in a dedicated thread.

    The low-level signal handler writes to this pipe immediately even while the
    main thread is inside AppKit. The worker can therefore preserve an active
    recording without waiting for the main thread to execute Python bytecode.
    """
    while True:
        data = os.read(shutdown_read_fd, 1)
        if not data:
            continue
        signum = data[0]
        handle_shutdown(signum, None)


def _install_shutdown_handling():
    global shutdown_read_fd, shutdown_write_fd

    shutdown_read_fd, shutdown_write_fd = os.pipe()
    os.set_blocking(shutdown_write_fd, False)
    signal.set_wakeup_fd(shutdown_write_fd)
    for signum in SHUTDOWN_SIGNALS:
        # Installing any Python handler activates the low-level wakeup-fd
        # write. The Python callback itself is intentionally a no-op; the
        # dedicated reader performs the real shutdown work.
        signal.signal(signum, lambda _signum, _frame: None)
    threading.Thread(
        target=shutdown_signal_loop,
        name="openspeaksy-signal-reader",
        daemon=True,
    ).start()


def _claim_job_completion(job_id):
    """
    Transition processing→idle ONLY if this specific job is still the current one.
    Prevents a stale worker (whose generation was bumped by a watchdog reset and
    a new recording cycle) from clobbering the active job's state or pasting old
    text into the user's current app.
    """
    global state, state_ts, current_hotkey, current_mode, current_wav_path
    with state_lock:
        if state == "processing" and current_job_id == job_id:
            state = "idle"
            state_ts = time.monotonic()
            current_hotkey = None
            current_mode = None
            current_wav_path = None
            return True
        return False


def _watchdog_tick():
    """
    Single watchdog pass. The hard recording limit is routed through the normal
    on_key_up path, which stops, atomically saves, and processes every captured
    sample. Processing timeout cleanup stays under state_lock so a fresh
    recording cannot start between the state reset and overlay cleanup.
    """
    global state, state_ts, current_job_id, current_hotkey, current_mode
    finish_keycode = None
    finish_reason = None

    with state_lock:
        elapsed = time.monotonic() - state_ts
        if state == "recording" and elapsed > RECORDING_TIMEOUT_SEC:
            finish_keycode = current_hotkey
            finish_reason = "hard recording limit"

        if state == "processing" and elapsed > PROCESSING_TIMEOUT_SEC:
            pending = current_wav_path
            log(
                f"watchdog: stuck in processing for {elapsed:.0f}s, resetting; "
                + (
                    f"recording preserved in .pending: {pending.name}"
                    if pending is not None
                    else "no pending recording tracked"
                )
            )
            state = "idle"
            state_ts = time.monotonic()
            current_job_id += 1
            current_hotkey = None
            current_mode = None
            # Surface the failure instead of silently dropping the spinner;
            # the background retry loop will re-transcribe the preserved WAV.
            overlay.flash_error("Transcription timed out, saved for retry")
            current_wav_path = None

    if finish_keycode is not None:
        log(
            f"watchdog: {finish_reason} after {elapsed:.0f}s; "
            "finalizing captured audio"
        )
        # on_key_up owns the normal stop → atomic save → worker path. If the
        # real key-up raced this call, its ownership check makes this a no-op.
        on_key_up(finish_keycode)


def watchdog_loop():
    while True:
        time.sleep(WATCHDOG_POLL_SEC)
        try:
            _watchdog_tick()
        except Exception as e:
            log(f"watchdog loop error: {e}")


PENDING_RETRY_POLL_SEC = 300


def pending_retry_loop():
    """
    Re-transcribe recordings that failed mid-session (dead network, provider
    outage) so they no longer wait for the next app restart. Mirrors startup
    recovery semantics: combined text goes to the clipboard only, never an
    unprompted paste. Runs only while idle and under _clipboard_gate so its
    clipboard write cannot race a live dictation paste.
    """
    while True:
        time.sleep(PENDING_RETRY_POLL_SEC)
        try:
            with state_lock:
                idle = state == "idle"
                has_pending = current_wav_path is None
            if not idle or not has_pending:
                continue
            with _clipboard_gate:
                with state_lock:
                    still_idle = state == "idle"
                if still_idle:
                    recover_pending_recordings()
        except Exception as e:
            log(f"pending retry loop error: {e}")


def copy_to_clipboard(text):
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    if not pb.setString_forType_(text, PB_TYPE):
        raise RuntimeError("pasteboard rejected transcription")


def paste_text(text):
    try:
        copy_to_clipboard(text)
        if not CGPreflightPostEventAccess():
            log("paste blocked: Accessibility permission is not trusted")
            return False
        time.sleep(0.05)

        for press in (True, False):
            e = CGEventCreateKeyboardEvent(None, V_KEY, press)
            CGEventSetFlags(e, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, e)

        return True
    except Exception as e:
        log(f"paste error: {e}")
        return False


def _ensure_pending_dir(pending_dir):
    pending_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(pending_dir, 0o700)
    except OSError as e:
        log(f"chmod pending dir error: {e}")


def save_pending_recording(audio, mode, pending_dir=None):
    """
    Encode mode in the filename so a crash between save and worker spawn doesn't
    lose the language/translate intent. Filename: ...-<uuid>.<mode>.wav. Legacy
    pre-upgrade files without the mode segment are treated as dictate by
    parse_pending_mode().
    """
    pending_dir = PENDING_DIR if pending_dir is None else Path(pending_dir)
    _ensure_pending_dir(pending_dir)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}.{mode}.wav"
    final = pending_dir / name
    tmp = pending_dir / (name + ".tmp")
    write_wav(audio, tmp)
    try:
        os.chmod(tmp, 0o600)
    except OSError as e:
        log(f"chmod pending file error: {e}")
    os.replace(tmp, final)  # atomic — recovery never sees a half-written WAV
    return final


def save_recording_with_fallback(audio, mode):
    """
    Persist to the project pending directory first, then to a private directory
    under ~/Library/Application Support if the project directory is
    unavailable. Callers must still surface an error if both locations fail.
    """
    try:
        return save_pending_recording(audio, mode)
    except Exception as primary_error:
        log(f"primary pending save failed: {primary_error}; trying fallback")
        try:
            path = save_pending_recording(
                audio, mode, pending_dir=FALLBACK_PENDING_DIR
            )
        except Exception as fallback_error:
            raise RuntimeError(
                "could not preserve recording in primary or fallback storage"
            ) from fallback_error
        log(f"recording preserved in fallback storage: {path.name}")
        return path


def parse_pending_mode(path):
    """
    Filename format: <timestamp>-<uuid>.<mode>.wav. Returns the mode if present,
    or MODE_DICTATE for legacy files (pre-upgrade) with no mode segment.
    """
    stem = path.stem  # strips final .wav
    for mode in (MODE_TRANSLATE, MODE_POLISH, MODE_DICTATE):
        if stem.endswith(f".{mode}"):
            return mode
    return MODE_DICTATE


def delete_pending_recording(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log(f"delete pending recording error {path.name}: {e}")


def quarantine_path(path, reason):
    quarantine_dir = (
        QUARANTINE_DIR
        if path.parent == PENDING_DIR
        else path.parent / "quarantine"
    )
    quarantine_dir.mkdir(exist_ok=True, mode=0o700)
    target = quarantine_dir / path.name
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


def error_notice(error):
    """
    A short, human notice for the overlay pill. Provider errors are written for
    logs ("HTTP Error 429: Too Many Requests"), which says nothing useful to
    someone who just spoke into their laptop. Where the provider told us how
    long to wait, that number is the single most useful thing to show.
    """
    text = str(error).strip()
    if not text:
        return "Transcription failed"

    wait = re.search(r"(?:frees up in|retry in)\s*([\d.]+)\s*s", text, re.IGNORECASE)
    if wait:
        seconds = int(float(wait.group(1)) + 0.5)
        return f"Rate limited, try again in {seconds}s"
    if "rate-limited" in text.lower() or "429" in text:
        return "Rate limited, try again shortly"
    if isinstance(error, ProviderUnavailableError):
        return "No connection to the transcription service"
    if "too large" in text.lower():
        return "Recording is too long to transcribe"
    if "api key" in text.lower():
        return "API key is missing or rejected"
    if "microphone" in text.lower():
        return "Microphone access is blocked in System Settings"

    # Unrecognized: show the provider's own words rather than swallowing them.
    # The overlay collapses whitespace and truncates, so a long one is safe.
    return text


def process_pending_recording(path, job_id, mode):
    """
    Live worker spawned by on_key_up. job_id is the generation token captured
    when the worker was scheduled; mode selects dictate vs translate.
    Recovery uses recover_pending_recordings instead — it has different rules
    around the clipboard.
    """
    text = None
    notice = None
    try:
        if mode == MODE_TRANSLATE:
            text = transcriber.transcribe_and_translate_sync(path)
        elif mode == MODE_POLISH:
            text = transcriber.transcribe_to_polish_sync(path)
        else:
            text = transcriber.transcribe_and_correct_sync(path, language=DICTATE_LANGUAGE)
    except TranscriptionError as e:
        log(f"transcription error {path.name}: {e}")
        notice = error_notice(e)
    except Exception as e:
        log(f"processing error {path.name}: {e}")
        notice = error_notice(e)

    # Claim ownership of THIS job — exact job_id match. A bare state check
    # would also accept a *newer* job's "processing" state and let a stale
    # worker paste old text into whatever the user is doing now. The claim
    # and the clipboard mutation share _clipboard_gate so the background
    # recovery pass can never interleave its own clipboard write between
    # this job's claim and its paste.
    with _clipboard_gate:
        if not _claim_job_completion(job_id):
            log(f"stale worker abandoned: {path.name}")
            return

        if notice:
            overlay.flash_error(notice)
            return  # keep file for retry

        if text:
            if paste_text(text):
                log(f"pasted {len(text)} chars from {path.name}")
                overlay.hide()
            else:
                overlay.flash_error("Could not paste into this app")
                return  # keep file
        else:
            log(f"no speech detected in {path.name}")
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
    pending_dirs = []
    for pending_dir in (PENDING_DIR, FALLBACK_PENDING_DIR):
        if pending_dir not in pending_dirs:
            pending_dirs.append(pending_dir)

    existing_dirs = [
        pending_dir for pending_dir in pending_dirs if pending_dir.is_dir()
    ]
    if not existing_dirs:
        return

    # Clean up partial writes from a previous crash mid-save
    for pending_dir in existing_dirs:
        for tmp in pending_dir.glob("*.tmp"):
            try:
                tmp.unlink()
                log(f"removed partial write: {tmp.name}")
            except OSError as e:
                log(f"remove partial write error {tmp.name}: {e}")

    paths = sorted(
        path
        for pending_dir in existing_dirs
        for path in pending_dir.glob("*.wav")
    )
    if not paths:
        return

    cutoff = time.time() - PENDING_AGE_WARN_DAYS * 86400
    stale = sum(1 for p in paths if p.stat().st_mtime < cutoff)
    if stale:
        log(
            f"WARNING: {stale} pending recording(s) older than "
            f"{PENDING_AGE_WARN_DAYS}d — transcription API may be unreachable"
        )

    log(f"found {len(paths)} pending recording(s)")
    recovered = []  # (path, text); text may be empty for hallucination/silence
    skipped = 0
    for index, path in enumerate(paths):
        if not is_valid_wav(path):
            quarantine_path(path, "corrupt WAV header")
            continue
        mode = parse_pending_mode(path)
        try:
            if mode == MODE_TRANSLATE:
                text = transcriber.transcribe_and_translate_sync(path)
            elif mode == MODE_POLISH:
                text = transcriber.transcribe_to_polish_sync(path)
            else:
                text = transcriber.transcribe_and_correct_sync(path, language=DICTATE_LANGUAGE)
        except ProviderUnavailableError as e:
            # Provider is unreachable; the remaining files stay pending and
            # the background retry loop will pick them up once it's back.
            log(f"recovery paused: provider unreachable ({e}); "
                f"{len(paths) - index} recording(s) pending")
            break
        except Exception as e:
            # A file-specific problem (e.g. the provider persistently returns
            # an empty transcript for this audio). Skip it so one poison file
            # can't block recovery of every other recording.
            log(f"recovery skipping {path.name}: {e}")
            skipped += 1
            continue
        recovered.append((path, text))

    non_empty = [(p, t) for p, t in recovered if t]

    if skipped:
        log(
            f"recovery skipped {skipped} recording(s) with file-specific "
            "errors; they stay in .pending"
        )

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


def _begin_recording(keycode, mode):
    """
    Atomic idle→recording transition that also latches the hotkey and mode
    in a single critical section. Splitting the state flip and the
    hotkey/mode write into two locks would leave a window in which a key-up
    can see the new "recording" state but the wrong (stale) hotkey/mode.
    Returns True on success.
    """
    global state, state_ts, current_job_id, current_hotkey, current_mode
    global current_wav_path
    with state_lock:
        if state != "idle":
            return False
        state = "recording"
        state_ts = time.monotonic()
        current_hotkey = keycode
        current_mode = mode
        current_wav_path = None
        return True


def _abandon_recording_cycle():
    """
    Drop a cycle that failed to launch (recorder.start error). Resets state to
    idle AND clears the hotkey/mode in a single critical section — separate
    set_state + clear would leave a window in which another keypress could
    start a new cycle that the second mutation then clobbers.
    """
    global state, state_ts, current_hotkey, current_mode
    with state_lock:
        if state == "recording":
            state = "idle"
            state_ts = time.monotonic()
        current_hotkey = None
        current_mode = None


def on_key_down(keycode, mode):
    if not _begin_recording(keycode, mode):
        return
    if _microphone_access_is_blocked():
        log(
            "recording blocked: Microphone permission is denied or restricted"
        )
        _abandon_recording_cycle()
        overlay.flash_error("Microphone access is blocked in System Settings")
        return
    try:
        recorder.start()
        log(f"recording started: mode={mode}")
        overlay.show("recording", label=MODE_LABELS.get(mode))
    except Exception as e:
        log(f"recorder.start error: {e}")
        _abandon_recording_cycle()
        overlay.flash_error("Could not start recording")


def on_key_up(keycode):
    # Ignore key-up for a hotkey that did NOT start the current cycle.
    # Without this, tapping the other hotkey mid-record would end the cycle.
    with state_lock:
        if current_hotkey != keycode:
            return

    # Atomically claim the recording→processing transition, capture the mode,
    # and allocate a fresh job_id. An old worker's claim must not match this
    # id even in the tiny window between state change and worker spawn.
    job_id, mode = begin_processing()
    if job_id is None:
        return

    try:
        audio = recorder.stop()
        log(f"recording stopped: {len(audio)} samples; mode={mode}")
    except Exception as e:
        log(f"recorder.stop error: {e}")
        if _claim_job_completion(job_id):
            overlay.flash_error("Recording failed")
        return

    if len(audio) < MIN_AUDIO_SAMPLES:
        log(
            f"recording ignored: {len(audio)} samples is below "
            f"{MIN_AUDIO_SAMPLES}-sample minimum"
        )
        overlay.hide()
        _claim_job_completion(job_id)
        return

    try:
        wav_path = save_recording_with_fallback(audio, mode)
    except Exception as e:
        log(f"save pending recording error: {e}")
        if _claim_job_completion(job_id):
            overlay.flash_error("Could not save the recording")
        return

    overlay.show("loading", label=MODE_LABELS.get(mode))
    global current_wav_path
    current_wav_path = wav_path
    try:
        threading.Thread(
            target=process_pending_recording,
            args=(wav_path, job_id, mode),
            daemon=True,
        ).start()
    except Exception as e:
        log(f"processing worker start error {wav_path.name}: {e}")
        current_wav_path = None
        if _claim_job_completion(job_id):
            overlay.flash_error("Could not start transcription")


def tap_callback(proxy, event_type, event, refcon):
    # Wrap entire body — Python exceptions from here propagate into the
    # CGEventTap C callback and can take down the run loop
    try:
        if event_type == kCGEventTapDisabledByTimeout or event_type == kCGEventTapDisabledByUserInput:
            CGEventTapEnable(tap_ref, True)
            log(f"event tap re-enabled (reason: {event_type})")
            return event

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        # Device-dependent flag distinguishes left vs right modifier —
        # the shared mask (e.g. kCGEventFlagMaskCommand) catches both
        if keycode == HOTKEY_KEYCODE:
            pressed = bool(CGEventGetFlags(event) & HOTKEY_FLAG)
            if pressed:
                on_key_down(keycode, MODE_DICTATE)
            else:
                on_key_up(keycode)
        elif keycode == TRANSLATE_KEYCODE:
            pressed = bool(CGEventGetFlags(event) & TRANSLATE_FLAG)
            if pressed:
                on_key_down(keycode, MODE_TRANSLATE)
            else:
                on_key_up(keycode)
        elif keycode == POLISH_KEYCODE:
            pressed = bool(CGEventGetFlags(event) & POLISH_FLAG)
            if pressed:
                on_key_down(keycode, MODE_POLISH)
            else:
                on_key_up(keycode)
    except Exception as e:
        log(f"tap_callback error: {e}")

    return event


def run_event_tap():
    global tap_ref, source_ref

    log(
        f"input monitoring trusted: {bool(CGPreflightListenEventAccess())}; "
        f"post events trusted: {bool(CGPreflightPostEventAccess())}"
    )
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


PLIST_HINT = (
    "~/Library/LaunchAgents/com.openspeaksy.plist (EnvironmentVariables) "
    "and reload."
)


def configuration_error():
    """
    Return a message describing the first fatal misconfiguration, or None when
    the config is usable. Pure so the rules can be tested without booting the
    event tap: main() only logs whatever this returns and exits.
    """
    if STT_BACKEND not in SUPPORTED_STT_BACKENDS:
        return (
            f"unsupported STT backend {STT_BACKEND!r}; expected one of "
            f"{sorted(SUPPORTED_STT_BACKENDS)}"
        )
    if POLISH_STT_BACKEND not in SUPPORTED_STT_BACKENDS:
        return (
            f"unsupported Polish STT backend {POLISH_STT_BACKEND!r}; "
            f"expected one of {sorted(SUPPORTED_STT_BACKENDS)}"
        )
    if "gemini" in {STT_BACKEND, POLISH_STT_BACKEND} and not GEMINI_API_KEYS:
        return (
            "no Gemini API key configured. Set GEMINI_API_KEYS (comma-"
            f"separated) or GEMINI_API_KEY in {PLIST_HINT}"
        )
    if "mistral" in {STT_BACKEND, POLISH_STT_BACKEND} and not MISTRAL_API_KEY:
        return (
            "STT backend is Mistral but no Mistral API key is configured. "
            f"Set MISTRAL_API_KEY in {PLIST_HINT}"
        )
    if not MISTRAL_API_KEY:
        return (
            "no Mistral API key configured; the translate hotkeys require it. "
            f"Set MISTRAL_API_KEY in {PLIST_HINT}"
        )
    return None


def main():
    # Private-by-default for logs, pending recordings, and any future files.
    os.umask(0o077)
    _install_file_handler()
    if not _acquire_instance_lock():
        log("another OpenSpeaksy instance is already running; exiting")
        return
    _install_shutdown_handling()

    fatal = configuration_error()
    if fatal:
        log(f"FATAL: {fatal}")
        os._exit(1)

    translator = f"Mistral {MISTRAL_TRANSLATION_MODEL}"
    if STT_BACKEND == "mistral":
        stt = f"Mistral {MISTRAL_MODEL}"
    elif STT_BACKEND == "gemini":
        stt = (
            f"Gemini {GEMINI_MODEL} ({len(GEMINI_API_KEYS)} key(s), "
            f"{GEMINI_REQUESTS_PER_WINDOW}/min each)"
        )
    else:
        stt = STT_BACKEND
    log(
        f"OpenSpeaksy starting — primary STT: {stt}; "
        f"dictate language: {DICTATE_LANGUAGE or 'auto'}; "
        f"Polish STT: {POLISH_STT_BACKEND}; translation backend: {translator}; "
        f"dictation correction: "
        f"{f'Mistral {MISTRAL_CORRECTION_MODEL}' if CORRECT_DICTATION else 'off'}"
    )
    microphone_status = microphone_authorization_status()
    if microphone_status in {
        MICROPHONE_AUTH_RESTRICTED,
        MICROPHONE_AUTH_DENIED,
    }:
        log(
            "ERROR: Microphone permission is denied or restricted; enable it "
            "in System Settings > Privacy & Security > Microphone"
        )
    elif microphone_status == MICROPHONE_AUTH_NOT_DETERMINED:
        log("microphone permission has not been requested yet")
    elif microphone_status == MICROPHONE_AUTH_AUTHORIZED:
        log("microphone permission trusted: True")

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # Recovery runs synchronously BEFORE the tap activates so a fresh dictation
    # cannot race the recovery clipboard write.
    recover_pending_recordings()

    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=pending_retry_loop, daemon=True).start()
    threading.Thread(target=run_event_tap, daemon=True).start()
    time.sleep(0.1)

    log(
        "OpenSpeaksy running — hold right Command (dictate), right Option "
        "(Russian→English), or right Shift (→Polish)"
    )
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
