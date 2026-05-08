<div align="center">

# OpenSpeaksy

**Free, fully local voice dictation for macOS.**
Hold right Command, speak, let go. The text appears in any app.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-lightgrey.svg)]()
[![100% local](https://img.shields.io/badge/100%25-local-success.svg)]()
[![Apple Neural Engine](https://img.shields.io/badge/Apple%20Neural%20Engine-accelerated-purple.svg)]()

</div>

---

- **Free forever.** MIT licensed. No accounts, no subscriptions, no telemetry.
- **Fully local.** Audio never leaves your Mac. No internet required after install.
- **Fast.** Whisper Large v3 on Apple Neural Engine — ~0.3 – 0.6 s for short phrases.
- **Multilingual.** Auto-detects language. Handles Russian, English, mixed speech well.
- **Reliable.** Recordings are queued to disk; nothing is lost if anything crashes.
- **Drop-in install.** Hand the repo to any AI coding agent — it sets everything up for you.

## Install

### One-prompt install (recommended)

Open **Claude Code**, **Codex CLI**, **Cursor**, or any AI coding agent. Paste this:

```
Install OpenSpeaksy on this Mac.

1. git clone git@github.com:sergeyizmailov/OpenSpeaksy.git ~/Documents/OpenSpeaksy
   (or use the HTTPS URL if SSH isn't set up)
2. cd ~/Documents/OpenSpeaksy
3. Read AGENTS.md and follow the install instructions there.
4. After ./scripts/install.sh finishes, tell me which exact paths I need to grant
   Input Monitoring and Accessibility permissions to in System Settings → Privacy & Security.
5. Verify the local server is up: curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8178/

Hardware: macOS on Apple Silicon. I already have Xcode CLT and Homebrew
(or help me install them if not).
```

The agent reads `AGENTS.md`, runs the installer, walks you through the two macOS permission prompts. About 5 minutes hands-free.

### Manual install

```bash
git clone git@github.com:sergeyizmailov/OpenSpeaksy.git
cd OpenSpeaksy
./scripts/install.sh
```

Then grant **Input Monitoring** and **Accessibility** to `venv/bin/python` in System Settings → Privacy & Security.

## Usage

Hold **right ⌘**, speak, release. Done. The transcription pastes into the focused text field and stays in your clipboard.

A small pill appears at the top of the screen:
- **Animated bars** while recording
- **Spinner** while transcribing
- **Red `!`** if anything fails

Recordings shorter than 1 second are skipped. Common Whisper hallucinations ("Subscribe", "Спасибо за просмотр", etc.) are filtered.

## Configuration

```bash
WHISPER_MODEL=large-v3-turbo ./scripts/install.sh   # ~4× faster, marginal quality drop
WHISPER_MODEL=medium         ./scripts/install.sh   # smaller and faster
WHISPER_CPP_REF=master       ./scripts/install.sh   # track upstream whisper.cpp HEAD
```

Tweak the hotkey, recording threshold, watchdog timeouts, or overlay style by editing `main.py` and `overlay.py` directly. The whole codebase is under 1000 lines.

## How it works

Two LaunchAgents run in the background:

| Service | Role |
|---|---|
| `com.openspeaksy.whisper` | `whisper-server` from whisper.cpp on `127.0.0.1:8178`, model resident in RAM, encoder loaded onto the Apple Neural Engine |
| `com.openspeaksy` | Python control process: CGEventTap for the hotkey, PortAudio for capture, NSPanel overlay, NSPasteboard + synthetic ⌘V for paste |

Recordings are written atomically to `.pending/` (mode `0700`, files `0600`) before transcription and deleted only after a successful paste. A watchdog auto-recovers stuck states. Per-job generation tokens prevent any stale worker from ever pasting old text into your current app — even if a watchdog reset and a new recording happen in between.

## Performance

On Apple M2, Whisper Large v3 with the Core ML encoder running on ANE:

| Audio length | Latency |
|---|---|
| 1 s | ~0.3 s |
| 5 s | ~0.6 s |
| 11 s (JFK sample) | ~1.7 s |
| 30 s | ~4 s |

ANE acceleration gives a 2 – 3× speedup over CPU-only on short dictation, where the encoder dominates.

## Logs

```bash
tail -f ~/Library/Logs/com.openspeaksy/main.log     # app log, rotated to 6 MB max
tail -f /tmp/openspeaksy-whisper.log                # whisper-server log
```

The app log captures startup health checks, watchdog events, errors, and recovery. Per-transcription chatter is intentionally suppressed for privacy and brevity.

## Uninstall

```bash
./scripts/uninstall.sh
```

Removes the LaunchAgents and logs. Project files, the model, and any queued recordings are left intact — delete the directory manually if you want a full wipe.

## Built on

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp) by Georgi Gerganov — the engine that does the actual work
- [OpenAI Whisper](https://github.com/openai/whisper) — the underlying model
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — for the macOS event tap and overlay

## License

MIT — see [LICENSE](LICENSE).
