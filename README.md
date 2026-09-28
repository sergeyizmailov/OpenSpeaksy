<div align="center">

<img src="docs/banner.jpg" alt="Speech to Text for macOS, powered by Mistral" width="720">

# OpenSpeaksy

A free, open-source speech-to-text script for macOS, built on [Mistral](https://mistral.ai).<br>
Bring your own API key. No app to buy, no subscription, no account.

[![CI](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml/badge.svg)](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

</div>

## How it works

A small Python script runs in the background. Hold a key and speak: the recording goes to Mistral with your key, and the text is pasted where your cursor is. Speech is transcribed by [Voxtral](https://docs.mistral.ai/capabilities/audio/), translation is done by Ministral. That's all there is to it.

## Keys

| Key | Action |
|:---|:---|
| Hold **right ⌘** | Dictate |
| **Right ⌥ + right ⌘** | Dictate hands-free. Tap right ⌘ to stop |
| Hold **right ⇧** | Speak Russian, paste English |
| **Caps Lock** | Cancel a transcription stuck for over 10 s. The audio is kept; double-tap to retry |

The text also stays in your clipboard. Short taps do nothing, so these keys still work in shortcuts.

## Install

You need macOS 13+ and a [Mistral API key](https://console.mistral.ai/api-keys). Mistral has a free plan that needs no card.

```bash
git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh
```

Paste the key when asked. Then open **System Settings → Privacy & Security** and allow `~/OpenSpeaksy/venv/bin/python` under **Input Monitoring** and **Accessibility**. Allow the microphone when asked on the first recording.

## Settings

Optional. Edit `EnvironmentVariables` in `~/Library/LaunchAgents/com.openspeaksy.plist`:

| Variable | Default | |
|:---|:---|:---|
| `OPENSPEAKSY_DICTATE_LANGUAGE` | auto | Force a dictation language, e.g. `en` |
| `MISTRAL_MODEL` | `voxtral-mini-2602` | Speech-to-text model |
| `MISTRAL_TRANSLATION_MODEL` | `ministral-8b-latest` | Translation model |

Then reload:

```bash
launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
launchctl load ~/Library/LaunchAgents/com.openspeaksy.plist
```

## Privacy

Audio goes to Mistral under your own key, and nowhere else. No telemetry. The key stays in that plist, readable by you alone, and transcripts are never logged. Each recording is saved to disk before it is sent, so a dropped connection retries it instead of losing it.

On Mistral's free plan your requests may be used to train their models. To turn that off: Mistral Admin → **Privacy** → disable **Anonymous improvement data** ([details](https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training)).

## Troubleshooting

| Problem | Fix |
|:---|:---|
| Nothing happens | Allow **Input Monitoring** for `venv/bin/python` |
| Records but doesn't paste | Allow **Accessibility** for `venv/bin/python` |
| Caps Lock also types capitals | System Settings → Keyboard → Modifier Keys → Caps Lock → **No Action** |
| Anything else | `tail -f ~/Library/Logs/com.openspeaksy/main.log` |

## Uninstall

```bash
./scripts/uninstall.sh
```

## License

[MIT](LICENSE). Not affiliated with Mistral AI.
