# OpenSpeaksy — instructions for AI coding agents

This file is the entry point for an LLM agent (Claude Code, Codex, Cursor,
ChatGPT desktop) installing or modifying OpenSpeaksy on a user's Mac.

## If the user asks you to install OpenSpeaksy

1. Confirm the host is **macOS** (`uname -s` should print `Darwin`).
2. Make sure the user has a Mistral API key
   (<https://console.mistral.ai/api-keys>). It is required for both
   speech-to-text (Voxtral) and the two translate hotkeys — not optional with
   the shipped defaults.
3. Run `./scripts/install.sh` from the repo root. It will prompt for the API
   key and write it into `~/Library/LaunchAgents/com.openspeaksy.plist`'s
   `EnvironmentVariables` (never to the repo). Set `MISTRAL_API_KEY=...`
   in the environment before running to skip its prompt.
4. After install, the user must manually grant **Input Monitoring** and
   **Accessibility** to `<repo>/venv/bin/python` in System Settings → Privacy
   & Security. Tell them which path to authorize. Do not try to do this
   yourself — there is no scripted path.
5. Verify by tailing `~/Library/Logs/com.openspeaksy/main.log` — you should
   see `OpenSpeaksy starting — primary STT: Mistral voxtral-mini-2602`.
6. Tell the user to hold right Command to dictate, right Option to dictate Russian and paste English, or right Shift to dictate Russian and paste Polish. Tapping Caps Lock cancels a transcription in flight (the audio is kept); tapping it twice quickly retries everything queued.

## If the user asks you to modify or debug OpenSpeaksy

Read these files in order — they are short and explicit:

- `main.py` — entry point, state machine, key handling, paste, watchdog, recovery
- `recorder.py` — PortAudio capture
- `transcriber.py` — Mistral STT plus the Mistral translation client
- `overlay.py` — NSPanel pill overlay
- `launchd/com.openspeaksy.plist.template` — LaunchAgent definition

Conventions in this codebase:

- **Single-source state**: the `state` global in `main.py` is mutated only
  through `_begin_recording(keycode, mode)`,
  `_abandon_recording_cycle()`, `begin_processing()`,
  `_claim_job_completion()`, `handle_shutdown()`, and the watchdog. Any new
  code that decides to
  paste, delete a pending file, or animate the overlay must claim ownership
  via these primitives first; stale workers that finish after a watchdog
  reset are explicitly designed to abort silently.
- **Per-cycle ownership**: `current_hotkey` is set in `_begin_recording` and
  cleared in `begin_processing`/`_abandon_recording_cycle`/watchdog. A key-up
  for a keycode that doesn't match `current_hotkey` is ignored — this is what
  prevents tapping the OTHER hotkey mid-record from ending the cycle.
- **Three hotkeys, one cycle**: right Cmd (`MODE_DICTATE`) routes through
  `transcribe_and_correct_sync` (Mistral STT → optional correction pass
  for transcripts ≥ `CORRECTION_MIN_CHARS`, gated by `CORRECT_DICTATION`);
  right Option (`MODE_TRANSLATE`) routes through
  `transcribe_and_translate_sync` (Mistral STT RU → Mistral translate);
  right Shift (`MODE_POLISH`)
  mirrors that flow through `transcribe_to_polish_sync` for RU → Polish. The
  mode is captured under `state_lock` in `_begin_recording` and consumed by
  `begin_processing`; it is also encoded in the pending filename
  (`...-{uuid}.{mode}.wav`) so a crash between save and worker spawn doesn't
  lose the intent.
- **Per-mode STT routing**: `OPENSPEAKSY_DICTATE_LANGUAGE` optionally forces a
  language hint for right Command; right Option always requests Russian;
  `OPENSPEAKSY_POLISH_STT_BACKEND` exists for interface parity but can only
  ever resolve to `mistral`; right Shift still forces Russian before the
  Mistral Polish translation.
- **Overlay labels reflect intent**: call `Overlay.show(mode, label=...)` with
  the value from `MODE_LABELS`. All modes share the same flat dark pill;
  translate modes add `English` or `Polish` above it. Errors show a message
  inside the pill, which resizes to the text (`_error_frame` measures it,
  wrapping at `ERROR_MAX_W`); `overlay.flash_error(message)` takes the text and
  `main.error_notice()` turns a raw provider error into it. Passing no message
  falls back to the old coral `!`.
- **Watchdog runs in its own thread** (`watchdog_loop`). State mutation and
  recorder/overlay cleanup stay under `state_lock` so a new recording cannot
  start between reset and cleanup. Overlay calls marshal asynchronously to the
  AppKit main loop.
- **No print() in production code** — all logging goes through `log()` in
  `main.py` (Python `logging` with `RotatingFileHandler`) or
  `logging.getLogger("openspeaksy")` in modules. Never log transcription
  contents — log lengths, paths, errors only. **Never log the API key.**
- **Cancel is a state-machine primitive**: Caps Lock (`CANCEL_KEYCODE`)
  calls `on_cancel_tap` → `cancel_everything()` / `resume_everything()`. It only acts on work that has been stuck for `CANCEL_GRACE_SEC`, since
  this key is also how capitals get typed: an in-flight job younger than that
  and a recording written more recently than that are both out of reach, and
  any tap that changes nothing returns in silence. One
  tap holds the queue in `_pending_cancelled` (which `_due_pending` skips); two
  taps inside `CANCEL_DOUBLE_TAP_SEC` release it. Cancelling a live job bumps
  `current_job_id` so its worker aborts, and a cancel while recording routes
  through `on_key_up` first so the audio still reaches disk. It must never
  delete a recording — only the retries stop.
  The tap subscribes to `kCGEventFlagsChanged` ONLY, so cancel has to be a
  modifier: an ordinary key (Escape, Space) would mean observing every
  keystroke the user types. Don't "improve" this into a normal key.
  Caps Lock is a TOGGLE — one press emits one event carrying the new state, so
  the handler fires on EVERY event for that keycode. Gating on the flag being
  set would act on every second press and make the double tap unreachable.
- **A failed recording is retried, not dropped**: the live worker schedules it
  via `_schedule_pending_retry` and the pill shows the countdown
  (`error_notice(error, retry_in=)`). Three per-file dicts pace this and must
  not be conflated: `_pending_failures` (gates quarantine, ignores outages),
  `_pending_attempt_count` (paces `PENDING_RETRY_BACKOFF_SEC`, counts
  everything), `_pending_next_attempt` (due time). `pending_retry_loop` wakes
  every `PENDING_RETRY_POLL_SEC` but only acts on `_due_pending`.
  Transport errnos (EPIPE/ECONNRESET/ETIMEDOUT/ENOTCONN) are
  `ProviderUnavailableError`, which pauses the sweep instead of counting the
  file as poison — do not reclassify them without re-reading why.
- **Recovery announces its clipboard write** with `overlay.flash_notice` and a
  sound, since it lands while the user may be elsewhere. Keep that call
  outside the clipboard try-block: the text is already safe, and a pill that
  cannot draw must not strand the audio.
- **Recovery is read-only and runs synchronously before the event tap**:
  startup recovery copies the transcript to the clipboard but **never**
  synthesizes Cmd+V. Focus at login is unrelated to the dictation context.
- **Atomic file writes**: WAVs go to `.pending/{name}.wav.tmp` then
  `os.replace()` to the final name. If the project directory is unavailable,
  the same atomic flow uses
  `~/Library/Application Support/OpenSpeaksy/pending/`.
  Recovery scans both locations, deletes orphan `.tmp` files, and quarantines
  corrupt WAVs beside the source directory.
- **Permissions**: `.pending/` is `0700`, files are `0600`. Don't loosen
  this without thinking about what dictated audio leaks imply.
- **One provider key**: `MISTRAL_API_KEY` does both speech-to-text (Voxtral)
  and translation/correction. There is nowhere to rotate to on a 429.
  `_chat_completion` (translate/correct/polish) passes
  `_request_json(..., retry_throttling=False)` — a 429 fails fast rather than
  spending the local retry budget on a request the account-level limit will
  refuse again immediately. The transcription call (`_transcribe_mistral`)
  keeps the default retry behavior, since a transient 429 there is still
  worth one bounded retry before the recording falls back to `.pending`.

If you change the LaunchAgent label (`com.openspeaksy`), also update
`LOG_DIR` in `main.py` and the launchctl commands in scripts/install.sh
and scripts/uninstall.sh.

If you change the project root, regenerate the plist by re-running
`./scripts/install.sh`. Plists embed absolute paths; symlinks won't help.

## Don't

- Don't add `print()` statements to "see what's happening" — use `log()`.
- Don't bypass the state-machine primitives — race conditions in this app
  paste old text into whatever the user is doing now, which is much worse
  than no paste at all.
- Don't hardcode the API key into the repo. The key lives only in
  `~/Library/LaunchAgents/com.openspeaksy.plist`'s `EnvironmentVariables`.
- Don't hardcode paths — the project must be relocatable. Use
  `Path(__file__).parent` or rely on `WorkingDirectory` set by launchd.
- Don't add a "restore old clipboard" feature — the user explicitly chose
  to always keep the transcription in the clipboard so recordings can never
  be silently lost.
- Don't log transcription text or the API key.
