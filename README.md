<div align="center">

# OpenSpeaksy

**Lightweight, private voice dictation and translation for macOS.**  
Powered by Gemini 3.5 Transcribe & Mistral Medium 3.5.

[![CI](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml/badge.svg)](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-lightgrey.svg)]()
[![Backend: Gemini](https://img.shields.io/badge/STT-Gemini%203.5%20Transcribe-black.svg)](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5-transcribe/)
[![Translation: Mistral](https://img.shields.io/badge/Translate-Mistral%20Medium-orange.svg)](https://docs.mistral.ai/)

<br>

<img src="docs/banner.png" alt="OpenSpeaksy" width="620">

</div>

---

## Overview

OpenSpeaksy is a native, open-source macOS menu-less background service for instant voice-to-text dictation and real-time translation. Bring your own API keys — no subscriptions, accounts, or telemetry.

| Feature | OpenSpeaksy | Typical Paid App |
|:---|:---|:---|
| **Pricing** | **Free & Open Source** (MIT) — BYO API keys | $10 – $15 / month |
| **Privacy** | 100% local daemon, zero tracking, keys in `0600` plist | Cloud telemetry & accounts |
| **STT Engine** | **Gemini 3.5 Transcribe** (85+ languages, jargon-aware) | Generic Whisper or proprietary |
| **Translation** | **Mistral Medium 3.5** (natural human phrasing) | Basic machine translation |
| **Reliability** | Atomic disk buffer, watchdog, background crash recovery | Audio lost on app crash |

---

## Hotkeys

Hold the key, speak, release. The text pastes directly into the active field and remains in your clipboard.

| Hotkey | Action | Description |
|:---|:---|:---|
| **Right ⌘** | **Dictate** | Transcribes spoken audio in any supported language with zero prompt bias. |
| **Right ⌥** | **Translate (EN)** | Dictate in Russian → pastes natural, idiomatic English. |
| **Right ⇧** | **Translate (PL)** | Dictate in Russian → pastes natural, idiomatic Polish. |

### Minimalist Dark Pill Overlay

A non-intrusive floating dark pill appears dynamically:
- **Audio meter**: Smooth animated voice bars while recording.
- **Spinner**: Calm spinning arc while processing API requests.
- **Error notices**: The pill expands to display readable status messages (e.g., *"Rate limited, try again in 34s"*) with exact server cooldown countdowns.

---

## Quick Install

### Prerequisites

1. **Gemini API Key(s)** — Get free keys at [Google AI Studio](https://aistudio.google.com/apikey). You can provide multiple keys (comma-separated) from different Google Cloud projects to multiply your requests-per-minute quota.
2. **Mistral API Key** — Get a key at [Mistral Console](https://console.mistral.ai/api-keys) for English and Polish translation.

---

### Method 1: AI Assistant Setup (Recommended)

Paste this prompt into **Claude Code**, **ChatGPT macOS**, or **Cursor**:

```text
Install OpenSpeaksy on this Mac:

git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh

The installer will ask for my Gemini and Mistral API keys — I'll paste them when prompted.
Then walk me through granting Input Monitoring and Accessibility permissions
in System Settings → Privacy & Security.
```

---

### Method 2: Manual Terminal Install

```bash
# 1. Clone the repository
git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy

# 2. Run the automated installer
./scripts/install.sh
```

During installation, paste your API keys. The installer sets up a isolated Python virtual environment and registers a `launchd` service at `~/Library/LaunchAgents/com.openspeaksy.plist`.

#### Grant macOS Permissions:

Go to **System Settings → Privacy & Security**:
- **Input Monitoring** → Enable for `~/OpenSpeaksy/venv/bin/python`
- **Accessibility** → Enable for `~/OpenSpeaksy/venv/bin/python`
- **Microphone** → Click **Allow** when prompted on your first recording.

To verify the daemon is running:
```bash
tail -f ~/Library/Logs/com.openspeaksy/main.log
```

---

## Configuration

Settings can be customized in `~/Library/LaunchAgents/com.openspeaksy.plist` under `EnvironmentVariables`:

| Variable | Default | Description |
|:---|:---|:---|
| `OPENSPEAKSY_STT_BACKEND` | `gemini` | Primary STT provider (`gemini` or `mistral`). |
| `GEMINI_API_KEYS` | *(from install)* | Comma-separated Gemini API keys for sliding-window rotation. |
| `GEMINI_MODEL` | `gemini-3.5-transcribe` | Gemini transcription model. |
| `OPENSPEAKSY_GEMINI_RPM` | `3` | Estimated RPM per key before automatic rotation. |
| `OPENSPEAKSY_GEMINI_EXHAUSTED_BACKEND` | `mistral` | Automatic fallback STT provider when all Gemini keys hit rate limits. |
| `MISTRAL_API_KEY` | *(from install)* | Mistral API key for translations. |
| `MISTRAL_TRANSLATION_MODEL` | `mistral-medium-3-5` | Model for Russian-to-English/Polish translations. |
| `MISTRAL_TRANSLATION_TEMPERATURE` | `0.2` | Temperature for natural conversational phrasing. |
| `OPENSPEAKSY_DICTATE_LANGUAGE` | `""` (auto) | Force dictation language (e.g., `ru`, `en`, `de`). |
| `OPENSPEAKSY_CORRECT_DICTATION` | `0` | Optional LLM correction pass for dictation (set `1` to enable). |

After modifying the plist, reload the service:
```bash
launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
launchctl load ~/Library/LaunchAgents/com.openspeaksy.plist
```

---

## Architecture & Reliability

- **Native macOS Integration**: Uses low-level Quartz `CGEventTap` and AppKit runloop with zero idle CPU overhead (~0.0% CPU, ~80 MB RAM).
- **Multi-Key Sliding-Window Rotation**: Distributes requests across Gemini keys and respects server-sent `Retry-After` headers and cooldowns.
- **Fail-Safe Voxtral Fallback**: If all Gemini keys are throttled, seamlessly falls back to Voxtral Mini Transcribe without dropping dictation.
- **Atomic File Buffering**: Audio is flushed to `.pending/*.wav` before network transmission. If network drops or the system crashes, pending recordings are recovered and copied to clipboard on next start.
- **Watchdog Protection**: Background watchdog resets stuck states and prevents dangling audio capture.
- **Privacy & Security**: Plist files are created with `0600` permissions. Transcribed text and API keys are never logged.

---

## Troubleshooting

| Symptom | Resolution |
|:---|:---|
| Hotkey ignored, nothing happens | Ensure **Input Monitoring** is granted to `venv/bin/python`. |
| Audio records but text does not paste | Ensure **Accessibility** is granted to `venv/bin/python`. |
| "Microphone access is blocked" notice | Enable microphone permission in **System Settings → Privacy & Security → Microphone**. |
| "Rate limited, try again in Xs" | All Gemini keys are temporarily throttled. Add more keys in `GEMINI_API_KEYS` to increase throughput. |
| Hotkey ignored in password fields | Expected when macOS Secure Input is active in sensitive input prompts. |

---

## Uninstallation

```bash
./scripts/uninstall.sh
```

Stops the service and removes the LaunchAgent plist and log files.

---

## License

MIT License — see [LICENSE](LICENSE).
