# Contributing to OpenSpeaksy

Thanks for your interest. OpenSpeaksy is small, opinionated, and intentionally
focused on macOS dictation — please read this before opening a PR.

## What's in scope

- macOS reliability and UX improvements
- New hotkey / overlay options
- Gemini/Mistral integration tweaks (rate-limit handling, model parameters)
- Documentation, install-script fixes, packaging
- Bug fixes with a clear repro

## What's out of scope

- Telemetry, analytics, account systems.
- Auto-pasting from startup recovery (privacy: focus is unrelated to the dictation context).
- Logging transcribed text or API keys.
- Major framework rewrites without prior discussion.

A Windows or Linux port is welcome but should live in a separate fork or a
clearly-isolated branch — see [Issue #1](https://github.com/sergeyizmailov/OpenSpeaksy/issues/1).

## Before sending a PR

1. Read [`AGENTS.md`](AGENTS.md). It documents the invariants the codebase
   relies on (state machine, per-job tokens, atomic writes, no-paste-on-recovery).
2. Run the checks locally:
   ```bash
   python -m py_compile main.py recorder.py transcriber.py overlay.py
   bash -n scripts/install.sh scripts/uninstall.sh
   plutil -lint launchd/*.plist.template
   pip install pytest && pytest tests/
   ```
3. If you change a state-machine invariant or add a side-effecting code path,
   add a test under `tests/`.
4. Match existing style — small functions, no `print()` in production code,
   no logging of transcribed text.

## Commit messages

Short imperative subject, then a paragraph explaining *why*. Bullet list of
changes if helpful. Example:

```
Stop an oversized recording from draining every Gemini key

The local size guard raised a plain TranscriptionError, so the key rotation
did not recognize it as a verdict on the payload and walked all three keys to
collect the same error once per key. Raising a distinct type keeps the guard
and the check from drifting apart again.
```

## Reporting bugs

Open an issue with:

- macOS version + Apple Silicon / Intel
- STT backend and model (`gemini` / `gemini-3.5-transcribe` by default)
- Reproduction steps
- Relevant lines from `~/Library/Logs/com.openspeaksy/main.log`

**Never paste transcribed text, audio, or API keys into an issue** —
those are private. Lengths, error messages, and paths are enough.
