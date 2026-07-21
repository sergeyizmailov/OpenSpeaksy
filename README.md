<div align="center">

# OpenSpeaksy

**Voice dictation for macOS, powered by ElevenLabs Scribe v2.**
Hold right Command, speak, let go. The text appears in any app.

[![CI](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml/badge.svg)](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-lightgrey.svg)]()
[![Backend: ElevenLabs](https://img.shields.io/badge/backend-ElevenLabs%20Scribe%20v2-black.svg)](https://elevenlabs.io/docs/overview/capabilities/speech-to-text)

<br>

<img src="docs/logo.png" alt="OpenSpeaksy" width="520">

</div>

---

## An open alternative to Wispr Flow, Superwhisper

Same idea with your own API credentials: ElevenLabs Scribe v2 handles transcription, while Groq powers the optional translation and Polish correction modes. No OpenSpeaksy account, ads, or tracking.

| | OpenSpeaksy | Typical paid app |
|---|---|---|
| Price | **MIT licensed** — bring your own API keys | $10 – 15 / month |
| Transcription latency | Network-dependent | similar |
| Account / signup | ElevenLabs key, plus Groq for transform modes | Required |
| Usage limits | Your providers' quotas | Daily / monthly caps |
| Ads & upsells | Never | Sometimes |
| Source code | Open | Closed |

---

## What you get

- **Open.** MIT licensed. No OpenSpeaksy account or telemetry; credentials stay in your local LaunchAgent plist.
- **Accurate.** ElevenLabs Scribe v2 provides multilingual speech recognition across 90+ languages.
- **Multilingual.** Auto-detects language. Handles Russian, English, mixed speech well.
- **Reliable.** Recordings are queued to disk; nothing is lost if the transcription service is unreachable.
- **Drop-in install.** Hand the repo to any AI coding agent — it sets everything up.

## Install

Pick the path that fits you. Both end up at the same place: a working install in about five minutes.

### Prerequisites — get API keys

Create an [ElevenLabs API key](https://elevenlabs.io/app/developers/api-keys) for Scribe v2 transcription. Create a [Groq API key](https://console.groq.com/keys) as well if you use Russian-to-English translation or Polish correction.

### Option A — One-prompt install (recommended if you don't use Terminal)

Open **Claude**, **ChatGPT**, **Cursor**, or any AI coding assistant. Paste this:

```
Install OpenSpeaksy on this Mac:

git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh

The installer will ask for my ElevenLabs and Groq API keys — I'll paste them when prompted.
Then walk me through granting Input Monitoring and Accessibility permissions
in System Settings → Privacy & Security.
```

The assistant runs the commands, asks for your key at the right moment, and tells you exactly which two switches to flip in System Settings. No Terminal knowledge needed.

### Option B — Manual install

If you'd rather drive the Terminal yourself:

**1.** Clone and run the installer:

```bash
git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh
```

When prompted, paste your ElevenLabs and Groq API keys and press Enter. The installer creates a Python venv, generates the LaunchAgent plist (stored at `0600` so only your user can read it), and starts the background service.

**2.** Grant macOS permissions. Open **System Settings → Privacy & Security**:

- **Input Monitoring** — turn on for `~/OpenSpeaksy/venv/bin/python`
- **Accessibility** — turn on the same binary
- **Microphone** — macOS will prompt on the first recording; click **Allow**

**3.** Try it. Hold right Command, say something, let go. The text appears wherever your cursor is.

To verify the service is running:

```bash
tail -f ~/Library/Logs/com.openspeaksy/main.log
```

You should see `OpenSpeaksy running — hold right Command (dictate) or right Option (Russian→English)`.

## Usage

Three hotkeys:

- **Right ⌘** — dictate. Speak in any language, the text pastes verbatim.
- **Right ⌥ (Option)** — dictate Russian, paste English. Scribe v2 transcribes in Russian, then an LLM (`llama-3.3-70b-versatile` on Groq) translates it before pasting.
- **Right ⇧ (Shift)** — dictate Russian or Polish, paste corrected Polish using the same transcription and Groq LLM pipeline.

Hold the key, speak, release. The text pastes into the focused field and stays in your clipboard.

A small dark pill appears near the bottom of the screen. All hotkeys share the same pill; transform modes add a thin label above it:

- **Pill, no label** — dictate (right ⌘)
- **Pill with "Translate" label** — translate (right ⌥)
- **Pill with "Polish" label** — Polish correction (right ⇧)
- **Animated bars** while recording, **spinner** while transcribing (or translating), **coral `!`** if a provider returns an error

Recordings shorter than 1 second are skipped. Common speech-model hallucinations ("Subscribe", "Спасибо за просмотр", etc.) are filtered out automatically.

## Configuration

### Change a hotkey

Two pairs of constants near the top of [`main.py`](main.py) — the dictate hotkey and the Russian→English translate hotkey:

```python
HOTKEY_KEYCODE    = 0x36   # right Command — dictate
HOTKEY_FLAG       = 0x10
TRANSLATE_KEYCODE = 0x3D   # right Option  — Russian → English
TRANSLATE_FLAG    = 0x40
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

### Tune providers and translate quality

The translate path (right ⌥) does Scribe v2 transcription → LLM translation → second LLM pass to polish phrasing on longer outputs. Environment variables in `~/Library/LaunchAgents/com.openspeaksy.plist` tune it without touching code:

| Variable | Default | Effect |
|---|---|---|
| `OPENSPEAKSY_STT_BACKEND` | `elevenlabs` | Primary STT provider: `elevenlabs` or retained `groq` fallback |
| `ELEVENLABS_MODEL` | `scribe_v2` | Primary speech-to-text model |
| `GROQ_MODEL` | `whisper-large-v3` | Speech-to-text model when the Groq fallback is selected |
| `GROQ_TRANSLATION_MODEL` | `llama-3.3-70b-versatile` | LLM used to translate + refine |
| `GROQ_TRANSLATION_TEMPERATURE` | `0.2` | Lower = more literal, higher = more natural phrasing |

After editing, reload the agent (`launchctl unload ... && launchctl load ...`).

### Rotate or change the API key

Edit `~/Library/LaunchAgents/com.openspeaksy.plist`, change `ELEVENLABS_API_KEY` or `GROQ_API_KEYS` (comma-separated for multiple Groq keys), then:

```bash
launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
launchctl load   ~/Library/LaunchAgents/com.openspeaksy.plist
```

## How it works

A single LaunchAgent (`com.openspeaksy`) runs `main.py`. It captures audio with PortAudio, watches for the hotkey via CGEventTap, persists each recording atomically to `.pending/`, POSTs the WAV to ElevenLabs Scribe v2, then writes the response to the clipboard and synthesizes ⌘V into the focused app.

Translate mode (right ⌥) asks Scribe v2 for Russian (`language_code="rus"`), then `llama-3.3-70b-versatile` translates the Russian to English. For outputs of 40+ characters, a second LLM call polishes awkward phrasing; if it errors, the first-pass translation is kept.

A separate watchdog thread auto-recovers stuck states. Per-job generation tokens prevent any stale worker from ever pasting old text into your current app — even if a watchdog reset and a new recording happen in between. The pending filename encodes the selected mode, so recovery after a crash preserves intent. If a provider is unreachable, the audio stays in `.pending/`; the next startup transcribes it and writes the combined result to the clipboard (it never auto-pastes — focus at login is unrelated to the dictation context).

## Performance

The Mac does almost nothing beyond audio capture and HTTPS requests. End-to-end latency depends on audio length, network conditions, and current provider load.

## Logs

```bash
tail -f ~/Library/Logs/com.openspeaksy/main.log     # app log, rotated to 6 MB max
```

Captures startup, watchdog events, errors, and recovery. Per-transcription text is intentionally never logged — only lengths, paths, and errors.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Hotkey ignored, nothing happens | Input Monitoring not granted to `venv/bin/python` |
| Recording works but text doesn't paste | Accessibility not granted to the same binary |
| No microphone prompt on first try | Microphone permission denied earlier — re-enable in System Settings |
| Coral `!` overlay every time | ElevenLabs/Groq key invalid, quota exhausted, or no internet — check the log |
| Hotkey ignored only in some apps (1Password, sudo prompts) | macOS Secure Input is active there; click out and back in |

For specifics, check the [log](#logs).

## Uninstall

```bash
./scripts/uninstall.sh
```

Removes the LaunchAgent and logs. Project files and any queued recordings are left intact — delete the directory manually if you want a full wipe.

## Built on

- [ElevenLabs Speech to Text](https://elevenlabs.io/docs/overview/capabilities/speech-to-text) — Scribe v2 transcription
- [Groq Chat Completions](https://console.groq.com/docs/api-reference) — optional translation and correction modes
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — for the macOS event tap and overlay

## License

MIT — see [LICENSE](LICENSE).
