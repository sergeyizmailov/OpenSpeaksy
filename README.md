<div align="center">

# OpenSpeaksy

**Free voice dictation for macOS, powered by the Groq Whisper API.**
Hold right Command, speak, let go. The text appears in any app.

[![CI](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml/badge.svg)](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-lightgrey.svg)]()
[![Backend: Groq](https://img.shields.io/badge/backend-Groq%20Whisper-orange.svg)](https://console.groq.com/)

<br>

<img src="docs/logo.png" alt="OpenSpeaksy" width="520">

</div>

---

## A free alternative to Wispr Flow, Superwhisper

Same idea — without the subscription. Bring your own free Groq API key, get sub-second transcriptions, no account on us, no ads, no tracking, source open.

| | OpenSpeaksy | Typical paid app |
|---|---|---|
| Price | **Free** (MIT) — bring your own Groq key | $10 – 15 / month |
| Transcription latency | ~0.2 – 0.5 s | similar |
| Account / signup | Groq free key, no OpenSpeaksy account | Required |
| Usage limits | Groq's free-tier daily quota | Daily / monthly caps |
| Ads & upsells | Never | Sometimes |
| Source code | Open | Closed |

---

## What you get

- **Free.** MIT licensed. No accounts, no subscriptions, no telemetry.
- **Fast.** Groq's LPU runs Whisper Large v3 in ~0.2 – 0.5 s for short phrases.
- **Multilingual.** Auto-detects language. Handles Russian, English, mixed speech well.
- **Reliable.** Recordings are queued to disk; nothing is lost if Groq is unreachable.
- **Drop-in install.** Hand the repo to any AI coding agent — it sets everything up.

> ⚠️ **Audio leaves your Mac.** OpenSpeaksy sends WAV to `api.groq.com` for transcription. If you need fully local, this branch isn't for you.

## Install

You'll need a free Groq API key — get one at [console.groq.com/keys](https://console.groq.com/keys).

### One-prompt install (recommended)

Open **Claude Code**, **Codex CLI**, **Cursor**, or any AI coding agent. Paste this:

```
Install OpenSpeaksy on this Mac:

git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh

The installer will ask for my Groq API key — I'll paste it when prompted.
Then walk me through granting Input Monitoring and Accessibility permissions
in System Settings → Privacy & Security.
```

### Manual install

```bash
git clone https://github.com/sergeyizmailov/OpenSpeaksy.git
cd OpenSpeaksy
./scripts/install.sh
# Paste your Groq API key when prompted
```

Then grant **Input Monitoring** and **Accessibility** to `venv/bin/python` in System Settings → Privacy & Security.

## Usage

Hold **right ⌘**, speak, release. Done. The transcription pastes into the focused text field and stays in your clipboard.

A small pill appears at the top of the screen:
- **Animated bars** while recording
- **Spinner** while transcribing
- **Red `!`** if Groq returns an error

Recordings shorter than 1 second are skipped. Common Whisper hallucinations ("Subscribe", "Спасибо за просмотр", etc.) are filtered.

## Configuration

### Change the hotkey

Default is **right Command**. Edit two constants near the top of [`main.py`](main.py):

```python
HOTKEY_KEYCODE = 0x36   # right Command
HOTKEY_FLAG    = 0x10   # left/right distinguishing flag
```

Common alternatives:

| Key | KEYCODE | FLAG |
|---|---|---|
| Right Command (default) | `0x36` | `0x10` |
| Left Command | `0x37` | `0x08` |
| Right Option | `0x3D` | `0x40` |
| Left Option | `0x3A` | `0x20` |
| Right Control | `0x3E` | `0x2000` |
| Right Shift | `0x3C` | `0x04` |

After editing, restart: `launchctl stop com.openspeaksy` (KeepAlive auto-restarts it).

### Rotate or change the API key

Edit `~/Library/LaunchAgents/com.openspeaksy.plist`, change the `GROQ_API_KEYS` value (comma-separated for multiple keys), then:

```bash
launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
launchctl load   ~/Library/LaunchAgents/com.openspeaksy.plist
```

### Multiple keys with auto-rotation

`GROQ_API_KEYS=key1,key2,key3` enables rotation: on HTTP 401/403/429 the worker advances to the next key and retries the same request. Useful for revoke/compromise scenarios. Note that Groq rate limits are per-organization, so multiple keys from one account share the daily quota — multiple accounts give you separate quotas.

### Model

Default is `whisper-large-v3`. To experiment, set `GROQ_MODEL` in the plist's `EnvironmentVariables` (`whisper-large-v3-turbo`, etc.). Stick with `large-v3` unless you know what you're doing — turbo loses precision on punctuation and proper nouns.

## How it works

A single LaunchAgent (`com.openspeaksy`) runs `main.py`. It captures audio with PortAudio, watches for the hotkey via CGEventTap, persists each recording to `.pending/` (mode `0700`, files `0600`), POSTs the WAV to `api.groq.com/openai/v1/audio/transcriptions`, then writes the response to the clipboard and synthesizes ⌘V into the focused app.

Recordings are written atomically (`.tmp` + `os.replace`) and deleted only after a successful paste. A separate watchdog thread auto-recovers stuck states every few seconds. Per-job generation tokens prevent any stale worker from ever pasting old text into your current app — even if a watchdog reset and a new recording happen in between. If Groq is unreachable, the audio stays in `.pending/`; the next startup transcribes it and writes the combined result to the clipboard (it never auto-pastes — focus at login is unrelated to the dictation context).

## Performance

On any modern Mac with reasonable network:

| Audio length | Latency |
|---|---|
| 1 s | ~0.2 s |
| 5 s | ~0.4 s |
| 11 s (JFK sample) | ~0.55 s |
| 30 s | ~1 s |

The Mac does almost nothing — capture and HTTP. The model lives on Groq's LPU.

## Logs

```bash
tail -f ~/Library/Logs/com.openspeaksy/main.log     # app log, rotated to 6 MB max
```

The app log captures startup, watchdog events, errors, and recovery. Per-transcription chatter is intentionally suppressed for privacy and brevity.

## Uninstall

```bash
./scripts/uninstall.sh
```

Removes the LaunchAgent and logs. Project files and any queued recordings are left intact — delete the directory manually if you want a full wipe.

## Built on

- [Groq Whisper API](https://console.groq.com/docs/speech-to-text) — `whisper-large-v3` on the LPU
- [OpenAI Whisper](https://github.com/openai/whisper) — the underlying model
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — for the macOS event tap and overlay

## License

MIT — see [LICENSE](LICENSE).
