# OpenSpeaksy — instructions for AI coding agents

This file is the entry point for an LLM agent (Claude Code, Codex, Cursor,
ChatGPT desktop) installing or modifying OpenSpeaksy on a user's Mac.

## If the user asks you to install OpenSpeaksy

1. Confirm the host is **macOS on Apple Silicon** (`uname -sm` should print
   `Darwin arm64`). On Intel, warn that ANE acceleration is unavailable; the
   app will still run via CPU fallback.
2. Confirm there is **at least 6 GB free disk** and **8 GB+ free RAM**
   (`df -h .` and `vm_stat`).
3. Run `./scripts/install.sh` from the repo root. The script is idempotent —
   safe to re-run.
4. After it finishes, the user must manually grant **Input Monitoring** and
   **Accessibility** to `<repo>/venv/bin/python` in System Settings → Privacy
   & Security. Tell them which paths to authorize. Do not try to do this
   yourself — there is no scripted path.
5. Wait until `tail -f /tmp/openspeaksy-whisper.log` shows `Core ML model loaded`
   (2 – 5 min on first start while the encoder is compiled for the chip).
6. Verify by curling the local server:
   `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8178/` →
   should return `200`.
7. Tell the user to hold right Command, speak, release. The transcription
   pastes into the focused field.

## If the user asks you to modify or debug OpenSpeaksy

Read these files in order — they are short and explicit:

- `main.py` — entry point, state machine, key handling, paste logic
- `recorder.py` — PortAudio capture
- `transcriber.py` — HTTP client to `whisper-server`
- `overlay.py` — NSPanel pill overlay
- `launchd/*.template` — LaunchAgent definitions

Conventions in this codebase:

- **Single-source state**: the `state` global in `main.py` is mutated only
  through `cas_state(expected, new)` and `set_state(new)`. Any new code that
  decides to paste, delete a pending file, or animate the overlay must claim
  ownership via CAS first; stale workers that finish after a watchdog reset
  are explicitly designed to abort silently.
- **No print() in production code** — all logging goes through `log()` in
  `main.py` (Python `logging` with `RotatingFileHandler`) or
  `logging.getLogger("openspeaksy")` in modules. Avoid logging transcription
  contents — log lengths, paths, errors only.
- **Recovery is read-only**: startup recovery copies the transcript to the
  clipboard but **never** synthesizes Cmd+V. Focus at login is unrelated to
  the dictation context.
- **Atomic file writes**: WAVs go to `.pending/{name}.wav.tmp` then
  `os.replace()` to the final name. The recovery scan deletes orphan `.tmp`
  files and quarantines corrupt WAVs to `.pending/quarantine/`.
- **Permissions**: `.pending/` is `0700`, files are `0600`. Don't loosen
  this without thinking about what dictated audio leaks imply.

If you change the LaunchAgent labels (`com.openspeaksy`, `com.openspeaksy.whisper`),
also update `WHISPER_LOG_PATH`, `LOG_DIR`, and the launchctl commands in
`main.py:check_log_sizes`.

If you change the project root, regenerate the plists by re-running
`./scripts/install.sh`. Plists embed absolute paths; symlinks won't help.

## Don't

- Don't add `print()` statements to "see what's happening" — use `log()`.
- Don't bypass `cas_state` — race conditions in this app paste old text into
  whatever the user is doing now, which is much worse than no paste at all.
- Don't hardcode paths — the project must be relocatable. Use
  `Path(__file__).parent` or rely on `WorkingDirectory` set by launchd.
- Don't ship a fine-tuned Whisper model in this repo. The model is a runtime
  asset downloaded by the installer.
- Don't add a "restore old clipboard" feature — the user explicitly chose to
  always keep the transcription in the clipboard so recordings can never be
  silently lost.
