# Contributing to OpenSpeaksy

Thanks for your interest. OpenSpeaksy is small, opinionated, and intentionally
focused on macOS dictation — please read this before opening a PR.

## What's in scope

- macOS reliability and UX improvements
- New hotkey / overlay options
- Whisper / whisper.cpp integration tweaks
- Documentation, install-script fixes, packaging
- Bug fixes with a clear repro

## What's out of scope

- Cloud transcription backends. The whole point is "fully local".
- Telemetry, analytics, account systems.
- Auto-pasting from startup recovery (privacy: focus is unrelated to the dictation context).
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
Collapse repeated transcripts and log paste length

Whisper occasionally emits the same short dictation twice with tiny
wording differences. SequenceMatcher with a 0.80 ratio on length-bucketed
input catches these without affecting genuinely distinct sentences.
```

## Reporting bugs

Open an issue with:

- macOS version + Apple Silicon / Intel
- Whisper model in use (`large-v3`, `large-v3-turbo`, etc.)
- Reproduction steps
- Relevant lines from `~/Library/Logs/com.openspeaksy/main.log` and
  `/tmp/openspeaksy-whisper.log`

**Never paste transcribed text or audio into an issue** — those are private.
Lengths, error messages, and paths are enough.
