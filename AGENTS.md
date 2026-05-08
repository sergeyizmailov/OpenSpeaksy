# OpenSpeaksy — instructions for AI coding agents

This file is the entry point for an LLM agent (Claude Code, Codex, Cursor,
ChatGPT desktop) installing or modifying OpenSpeaksy on a user's Mac.

## If the user asks you to install OpenSpeaksy

1. Confirm the host is **macOS** (`uname -s` should print `Darwin`).
2. Make sure the user has a Groq API key. If not, send them to
   <https://console.groq.com/keys> to create a free one.
3. Run `./scripts/install.sh` from the repo root. It will prompt for the API
   key and write it into `~/Library/LaunchAgents/com.openspeaksy.plist`'s
   `EnvironmentVariables` (never to the repo). Set `GROQ_API_KEYS=...` in the
   environment before running to skip the prompt.
4. After install, the user must manually grant **Input Monitoring** and
   **Accessibility** to `<repo>/venv/bin/python` in System Settings → Privacy
   & Security. Tell them which path to authorize. Do not try to do this
   yourself — there is no scripted path.
5. Verify by tailing `~/Library/Logs/com.openspeaksy/main.log` — you should
   see `OpenSpeaksy starting — backend: Groq cloud (1 key(s))`.
6. Tell the user to hold right Command, speak, release.

## If the user asks you to modify or debug OpenSpeaksy

Read these files in order — they are short and explicit:

- `main.py` — entry point, state machine, key handling, paste, watchdog, recovery
- `recorder.py` — PortAudio capture
- `transcriber.py` — Groq HTTP client with multi-key rotation
- `overlay.py` — NSPanel pill overlay
- `launchd/com.openspeaksy.plist.template` — LaunchAgent definition

Conventions in this codebase:

- **Single-source state**: the `state` global in `main.py` is mutated only
  through `cas_state(expected, new)`, `set_state(new)`, `begin_processing()`,
  `_claim_job_completion()`, and the watchdog. Any new code that decides to
  paste, delete a pending file, or animate the overlay must claim ownership
  via these primitives first; stale workers that finish after a watchdog
  reset are explicitly designed to abort silently.
- **Watchdog runs in its own thread** (`watchdog_loop`). State mutation
  happens under the lock; resource cleanup (recorder, overlay) happens
  outside the lock since those calls can block or marshal to the main loop.
- **No print() in production code** — all logging goes through `log()` in
  `main.py` (Python `logging` with `RotatingFileHandler`) or
  `logging.getLogger("openspeaksy")` in modules. Never log transcription
  contents — log lengths, paths, errors only. **Never log the API key.**
- **Recovery is read-only and runs synchronously before the event tap**:
  startup recovery copies the transcript to the clipboard but **never**
  synthesizes Cmd+V. Focus at login is unrelated to the dictation context.
- **Atomic file writes**: WAVs go to `.pending/{name}.wav.tmp` then
  `os.replace()` to the final name. The recovery scan deletes orphan `.tmp`
  files and quarantines corrupt WAVs to `.pending/quarantine/`.
- **Permissions**: `.pending/` is `0700`, files are `0600`. Don't loosen
  this without thinking about what dictated audio leaks imply.
- **Groq quirks**: the `Authorization: Bearer ...` header is required, and
  the default Python `urllib` User-Agent gets HTTP 403 from Groq's WAF —
  override with any non-default value (we use `openspeaksy/1.0`).

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
