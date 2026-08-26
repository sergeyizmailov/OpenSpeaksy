<div align="center">

# OpenSpeaksy

**Voice dictation for macOS, powered by Gemini 3.5 Transcribe.**
Hold right Command, speak, let go. The text appears in any app.

[![CI](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml/badge.svg)](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-lightgrey.svg)]()
[![Backend: Gemini](https://img.shields.io/badge/backend-Gemini%203.5%20Transcribe-black.svg)](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5-transcribe/)

<br>

<img src="docs/logo.png" alt="OpenSpeaksy" width="520">

</div>

---

## An open alternative to Wispr Flow, Superwhisper

Same idea with your own API credentials: Gemini 3.5 Transcribe handles transcription, while Mistral Medium 3.5 translates Russian into English or Polish. No OpenSpeaksy account, ads, or tracking.

| | OpenSpeaksy | Typical paid app |
|---|---|---|
| Price | **MIT licensed** — bring your own API keys | $10 – 15 / month |
| Transcription latency | Network-dependent | similar |
| Account / signup | One Mistral key | Required |
| Usage limits | Your providers' quotas | Daily / monthly caps |
| Ads & upsells | Never | Sometimes |
| Source code | Open | Closed |

---

## What you get

- **Open.** MIT licensed. No OpenSpeaksy account or telemetry; credentials stay in your local LaunchAgent plist.
- **Accurate.** Gemini 3.5 Transcribe covers 85+ languages and handles domain jargon without a custom vocabulary list.
- **Multilingual.** Auto-detects supported languages and handles Russian and English well.
- **Reliable.** Recordings are queued to disk; nothing is lost if the transcription service is unreachable.
- **Drop-in install.** Hand the repo to any AI coding agent — it sets everything up.

## Install

Pick the path that fits you. Both end up at the same place: a working install in about five minutes.

### Prerequisites — two required API keys

- **Gemini (required):** create a [Gemini API key](https://aistudio.google.com/apikey) for speech-to-text. The free tier allows 3 requests per minute per project, so you can create keys in several Google projects and paste them comma-separated to raise that ceiling.
- **Mistral (required):** create a [Mistral API key](https://console.mistral.ai/api-keys) for Mistral Medium translation on the two translate hotkeys.

### Option A — One-prompt install (recommended if you don't use Terminal)

Open **Claude**, **ChatGPT**, **Cursor**, or any AI coding assistant. Paste this:

```
Install OpenSpeaksy on this Mac:

git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh

The installer will ask for my Gemini and Mistral API keys — I'll paste them when prompted.
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

When prompted, paste your Gemini API key (or several, comma-separated) and your Mistral API key. The installer creates a Python venv, generates the LaunchAgent plist (stored at `0600` so only your user can read it), and starts the background service.

**2.** Grant macOS permissions. Open **System Settings → Privacy & Security**:

- **Input Monitoring** — turn on for `~/OpenSpeaksy/venv/bin/python`
- **Accessibility** — turn on the same binary
- **Microphone** — macOS will prompt on the first recording; click **Allow**

**3.** Try it. Hold right Command, say something, let go. The text appears wherever your cursor is.

To verify the service is running:

```bash
tail -f ~/Library/Logs/com.openspeaksy/main.log
```

You should see `OpenSpeaksy running — hold right Command (dictate), right Option (Russian→English), or right Shift (→Polish)`.

## Usage

Three hotkeys:

- **Right ⌘** — dictate in any language Gemini Transcribe supports; the text pastes verbatim.
- **Right ⌥ (Option)** — dictate Russian, paste English. Gemini transcribes in Russian, then Mistral Medium translates it before pasting.
- **Right ⇧ (Shift)** — dictate Russian, paste Polish. Gemini transcribes with `language="ru"`, then Mistral Medium translates the result into Polish.

Hold the key, speak, release. The text pastes into the focused field and stays in your clipboard.

A small dark pill appears near the bottom of the screen. All hotkeys share the same pill; transform modes add a thin label above it:

- **Pill, no label** — dictate (right ⌘)
- **Pill with "English" label** — Russian-to-English translation (right ⌥)
- **Pill with "Polish" label** — Russian-to-Polish translation (right ⇧)
- **Animated bars** while recording, **spinner** while transcribing (or translating), and a **message** if something fails — the pill widens and wraps to fit the text, and stays up long enough to read it. When a provider reports how long to wait, that is what it says ("Rate limited, try again in 39s")

Recordings shorter than 0.8 seconds are skipped. Common speech-model
hallucinations ("Subscribe", "Спасибо за просмотр", etc.) are filtered out
automatically.

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

The translate path (right ⌥) does Gemini transcription → Mistral translation, one LLM call each. Environment variables in `~/Library/LaunchAgents/com.openspeaksy.plist` tune it without touching code:

| Variable | Default | Effect |
|---|---|---|
| `OPENSPEAKSY_STT_BACKEND` | `gemini` | STT provider: `gemini` or `mistral` |
| `OPENSPEAKSY_DICTATE_LANGUAGE` | empty | Language hint for right Command; empty means auto-detect, `ru` forces Russian |
| `OPENSPEAKSY_POLISH_STT_BACKEND` | inherits `OPENSPEAKSY_STT_BACKEND` | STT provider used only by right Shift; the language hint is always Russian |
| `MISTRAL_MODEL` | `voxtral-mini-2602` | Primary speech-to-text model |
| `MISTRAL_TRANSLATION_MODEL` | `mistral-medium-3-5` | Model used to translate into English/Polish |
| `MISTRAL_TRANSLATION_TEMPERATURE` | `0.2` | Lower = more literal, higher = more natural phrasing |
| `GEMINI_API_KEYS` | empty | Comma-separated Gemini keys. The free per-minute quota is metered per project, so each key adds its own allowance |
| `GEMINI_API_KEY` | empty | Single Gemini key. Appended to `GEMINI_API_KEYS`; duplicates are dropped |
| `GEMINI_MODEL` | `gemini-3.5-transcribe` | Model used when the STT backend is `gemini` |
| `OPENSPEAKSY_GEMINI_RPM` | `3` | Requests per minute assumed available per key; the limiter diverts to the next key before the provider rejects the call |
| `OPENSPEAKSY_GEMINI_EXHAUSTED_BACKEND` | `mistral` | Backend used when every Gemini key is rate-limited. Empty string makes the dictation fail instead |
| `OPENSPEAKSY_CORRECT_DICTATION` | `0` | Set to `1` for a second LLM pass that cleans up dictation; off by default because it also normalizes domain jargon into different words |
| `MISTRAL_CORRECTION_MODEL` | `mistral-medium-3-5` | Model used by the dictation cleanup pass |
| `MISTRAL_CORRECTION_TEMPERATURE` | `0.0` | Raising it was measured to let the model invert the speaker's meaning; leave it alone |
| `OPENSPEAKSY_CORRECTION_MIN_CHARS` | `40` | Transcripts shorter than this skip correction — too little context, most visible latency |

The `gemini` backend uses Gemini 3.5 Transcribe through Google's Interactions API
(`POST /v1beta/interactions`), not the `generateContent` endpoint the rest of Gemini
uses. That endpoint accepts the request for this model and returns an empty result.
The request carries the audio and nothing else: this model only transcribes, and a
text instruction was measured to change nothing, so none is sent. Translation stays
on Mistral regardless of the STT backend, so `MISTRAL_API_KEY` is still required
alongside the Gemini keys.

Measured on this host it transcribes Russian media-buying jargon noticeably better
than Voxtral, but takes about 3 s against Voxtral's 0.5 s. That cost is fixed
overhead rather than processing time (2 s of audio takes 3.3 s, 8.6 s takes 3.6 s),
so shorter recordings do not help. The free tier allows only **3 requests per minute
per project**, so list several keys in `GEMINI_API_KEYS`: each request takes the
first key with quota left, giving 9 dictations per minute across three keys. A key
that returns HTTP 429 is abandoned immediately rather than retried, and it is held on
cooldown for as long as the provider's own retry hint asks. That hint matters: the free
tier enforces a second, longer-window cap (reported as `limit: 25`) that counting our
own requests cannot see, so without it the limiter resumes against a key Google still
refuses.

When every key is throttled, transcription falls back to Voxtral
(`OPENSPEAKSY_GEMINI_EXHAUSTED_BACKEND`), which has no comparable ceiling: a 0.5 s
transcript with weaker jargon handling beats no paste at all. Set that variable to an
empty string to fail instead, in which case the recording stays in `.pending/` and is
recovered on the next start. Either way no audio is lost.

After editing, reload the agent (`launchctl unload ... && launchctl load ...`).

### Rotate or change the API key

Edit `~/Library/LaunchAgents/com.openspeaksy.plist`, change `GEMINI_API_KEYS` or `MISTRAL_API_KEY`, then:

```bash
launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
launchctl load   ~/Library/LaunchAgents/com.openspeaksy.plist
```

## How it works

A single LaunchAgent (`com.openspeaksy`) runs `main.py`. A process lock prevents a manual second launch from registering duplicate hotkeys or pasting twice. It captures audio with PortAudio, watches for the hotkey via CGEventTap, persists each recording atomically to `.pending/`, POSTs the WAV to Gemini Transcribe, then writes the response to the clipboard and synthesizes ⌘V into the focused app.

Dictate mode (right ⌘) pastes the transcript as-is. An optional cleanup pass is available but **off by default** (`OPENSPEAKSY_CORRECT_DICTATION=1` enables it): for transcripts of 40+ characters it sends the text to `mistral-medium-3-5`. Fast recognition is lossy: it mishears words, swallows endings, drops short words, and cuts phrases off mid-thought, so sentences read as broken even when the speaker was clear. The pass infers the subject matter of the text and uses it to repair misheard words and mangled product names, restore what was dropped, finish cut-off phrases, split run-on speech into sentences, and reword phrasing that is barely grammatical — while keeping the speaker's own wording, tone, and register, and never adding facts the speaker did not say.

The result is accepted only if it still looks like a cleanup of the original: markdown and wrapping quotes are stripped, growth beyond 60% is discarded as an answer rather than an edit, and shrinkage beyond 50% as a summary. Both bounds are loose on purpose — collapsing spelled-out numbers into digits and tightening rambling speech are wanted, so the guard only catches a model that stopped editing and started writing its own text. Any failure or rejection pastes the raw transcript, so the pass can never cost you a recording. It adds roughly 0.5 s on a short phrase and 20 s on a 13-minute recording, since its cost tracks transcript length rather than audio length.

Translate mode (right ⌥) asks Gemini for Russian (`language="ru"`), then `mistral-medium-3-5` translates the Russian to English. One LLM call, no second polishing pass: the translation prompt already targets natural, human phrasing.

Polish mode (right ⇧) mirrors translate mode: it requests Russian transcription (`language="ru"`), then asks Mistral Medium for a Polish translation. `OPENSPEAKSY_POLISH_STT_BACKEND` can select a different STT provider without changing that Russian-only contract.

A separate watchdog thread auto-recovers stuck states. Per-job generation tokens prevent any stale worker from ever pasting old text into your current app — even if a watchdog reset and a new recording happen in between. The pending filename encodes the selected mode, so recovery after a crash preserves intent. If `.pending/` cannot be written, OpenSpeaksy atomically saves to a private fallback directory under `~/Library/Application Support/OpenSpeaksy/pending/`. If a provider is unreachable, the audio remains queued; the next startup transcribes it and writes the combined result to the clipboard (it never auto-pastes — focus at login is unrelated to the dictation context).

OpenSpeaksy never automatically removes repeated sentences from a transcript: an intentional repetition is indistinguishable from a model duplication, so preserving every recognized word takes priority.

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
| No microphone prompt on first try | Microphone permission denied earlier — re-enable it in System Settings → Privacy & Security → Microphone |
| Coral `!` appears immediately when recording starts | Microphone access is denied/restricted, or Core Audio could not open the input device |
| Coral `!` overlay every time | Mistral/selected STT key invalid, quota exhausted, or no internet — check the log |
| Hotkey ignored only in some apps (1Password, sudo prompts) | macOS Secure Input is active there; click out and back in |

For specifics, check the [log](#logs).

## Uninstall

```bash
./scripts/uninstall.sh
```

Removes the LaunchAgent and logs. Project files and any queued recordings are left intact — delete the directory manually if you want a full wipe.

## Built on

- [Gemini 3.5 Transcribe](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5-transcribe/) — speech-to-text
- [Mistral Audio Transcriptions](https://docs.mistral.ai/models/model-cards/voxtral-mini-transcribe-26-02) — Voxtral Mini Transcribe 2, the alternate STT backend
- [Mistral Medium 3.5](https://docs.mistral.ai/models/model-cards/mistral-medium-3-5-26-04) — Russian-to-English/Polish translation
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — for the macOS event tap and overlay

## License

MIT — see [LICENSE](LICENSE).
