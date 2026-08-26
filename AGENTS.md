# OpenSpeaksy — instructions for AI coding agents

This file is the entry point for an LLM agent (Claude Code, Codex, Cursor,
ChatGPT desktop) installing or modifying OpenSpeaksy on a user's Mac.

## If the user asks you to install OpenSpeaksy

1. Confirm the host is **macOS** (`uname -s` should print `Darwin`).
2. Make sure the user has a Mistral API key. If not, send them to
   <https://console.mistral.ai/api-keys>. The same key powers Voxtral
   transcription and Mistral Medium translation.
3. Run `./scripts/install.sh` from the repo root. It will prompt for the API
   keys and write them into `~/Library/LaunchAgents/com.openspeaksy.plist`'s
   `EnvironmentVariables` (never to the repo). Set `MISTRAL_API_KEY=...`
   in the environment before running to skip its prompt, and
   `GEMINI_API_KEYS=key1,key2` to skip the Gemini prompt.
4. After install, the user must manually grant **Input Monitoring** and
   **Accessibility** to `<repo>/venv/bin/python` in System Settings → Privacy
   & Security. Tell them which path to authorize. Do not try to do this
   yourself — there is no scripted path.
5. Verify by tailing `~/Library/Logs/com.openspeaksy/main.log` — you should
   see `OpenSpeaksy starting — primary STT: Mistral voxtral-mini-2602`.
6. Tell the user to hold right Command to dictate, right Option to dictate Russian and paste English, or right Shift to dictate Russian and paste Polish.

## If the user asks you to modify or debug OpenSpeaksy

Read these files in order — they are short and explicit:

- `main.py` — entry point, state machine, key handling, paste, watchdog, recovery
- `recorder.py` — PortAudio capture
- `transcriber.py` — Gemini/Mistral STT plus the Mistral Medium translation client
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
  `transcribe_and_correct_sync` (selected STT backend → optional correction pass
  for transcripts ≥ `CORRECTION_MIN_CHARS`, gated by `CORRECT_DICTATION`);
  right Option (`MODE_TRANSLATE`) routes through
  `transcribe_and_translate_sync` (Gemini RU → Mistral translate → optional
  refine pass for outputs ≥ `REFINE_MIN_CHARS`); right Shift (`MODE_POLISH`)
  mirrors that flow through `transcribe_to_polish_sync` for RU → Polish. The
  mode is captured under `state_lock` in `_begin_recording` and consumed by
  `begin_processing`; it is also encoded in the pending filename
  (`...-{uuid}.{mode}.wav`) so a crash between save and worker spawn doesn't
  lose the intent.
- **Per-mode STT routing**: `OPENSPEAKSY_DICTATE_LANGUAGE` optionally forces a
  language hint for right Command; right Option always requests Russian;
  `OPENSPEAKSY_POLISH_STT_BACKEND` independently selects the right-Shift STT
  provider; right Shift still forces Russian before the Mistral Polish translation.
- **Overlay labels reflect intent**: call `Overlay.show(mode, label=...)` with
  the value from `MODE_LABELS`. All modes share the same flat dark pill;
  translate modes add `English` or `Polish` above it. Errors show a coral `!`.
- **Watchdog runs in its own thread** (`watchdog_loop`). State mutation and
  recorder/overlay cleanup stay under `state_lock` so a new recording cannot
  start between reset and cleanup. Overlay calls marshal asynchronously to the
  AppKit main loop.
- **No print() in production code** — all logging goes through `log()` in
  `main.py` (Python `logging` with `RotatingFileHandler`) or
  `logging.getLogger("openspeaksy")` in modules. Never log transcription
  contents — log lengths, paths, errors only. **Never log the API key.**
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
- **Two provider keys in play**: `GEMINI_API_KEYS` (comma-separated) does all
  speech-to-text; `MISTRAL_API_KEY` does translation only. Translation ALWAYS
  goes to Mistral, so its key is required whatever `OPENSPEAKSY_STT_BACKEND` is.
  Mistral Voxtral stays wired as the alternate STT backend but is unused.
- **Gemini quota is per project, so keys are a resource**: each key in
  `GEMINI_API_KEYS` gets its own `_SlidingWindowQuota` and a request takes the
  first key with room. Adding a key raises the ceiling; reusing one does not
  (duplicates are dropped). A 429 abandons that key immediately rather than
  retrying it, via `_request_json(..., retry_throttling=False)` — do not extend
  that flag to other providers, where waiting out a 429 is still correct.
- **Gemini STT is not the usual Gemini endpoint**: `gemini-3.5-transcribe` is
  called through `POST /v1beta/interactions`, and the transcript is nested in
  `steps[].content[].text`. `generateContent` returns HTTP 200 with an empty
  part for this model instead of failing, so a wrong endpoint looks like a
  silent model rather than an error. See `.notes/index.md` for the full
  contract, including why a missing `steps` key means silence.

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
