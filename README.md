<div align="center">

# OpenSpeaksy

**Free voice typing for Mac.**
Hold right Command, speak, let go — your words appear in any app.

[![CI](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml/badge.svg)](https://github.com/sergeyizmailov/OpenSpeaksy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-lightgrey.svg)]()

<br>

<img src="docs/logo.png" alt="OpenSpeaksy" width="520">

</div>

---

## A free alternative to Wispr Flow & Superwhisper

Same idea — without the monthly fee. Type with your voice in any Mac app, in any language.

| | OpenSpeaksy | Paid apps |
|---|---|---|
| Price | **Free** | $10 – 15 / month |
| Speed | Under half a second | Similar |
| Account | None needed on our side | Required |
| Ads | Never | Sometimes |

You only need a free key from Groq (the company that does the actual voice-to-text). It takes 30 seconds to get one and there's no payment.

## Install (5 minutes)

**Step 1.** Get a free key at [console.groq.com/keys](https://console.groq.com/keys). Click **Create API Key**, copy the long `gsk_...` string.

**Step 2.** Open **Claude**, **ChatGPT**, **Cursor**, or any AI coding assistant, and paste this:

> Install OpenSpeaksy from <https://github.com/sergeyizmailov/OpenSpeaksy> on this Mac. I have a Groq API key ready to paste when the installer asks. After install, walk me through turning on Input Monitoring and Accessibility in System Settings → Privacy & Security.

The assistant will run the commands, ask for your key, and tell you exactly which two switches to flip in System Settings. No Terminal knowledge needed.

**Step 3.** Hold right Command, talk, let go. Done.

<details>
<summary>Prefer the Terminal?</summary>

```bash
git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh
```

Paste the key when prompted. Then in **System Settings → Privacy & Security**, turn on **Input Monitoring** and **Accessibility** for `python` (you'll find it in the list).

</details>

## How to use

Hold **right ⌘**, speak, let go. The text appears wherever you're typing.

A tiny pill at the top of the screen shows what's happening:
- Bars dancing → recording
- Spinner → transcribing
- Red `!` → something went wrong

Works in any app — Chrome, Slack, Notes, Word, Telegram, anywhere you can type.

## Heads-up

- **Your audio goes to Groq's servers** for transcription, then is discarded. If you need everything to stay on your Mac, this isn't the app for you.
- Keep your API key private — it's saved locally on your Mac, but anyone with that string can use your free quota.
- The free Groq tier has a daily quota that resets every 24 hours. For normal personal use you'll never hit it.

## Want a different hotkey?

By default it's **right Command**. To use a different key, see [`main.py`](main.py) — there's a small table at the top with options for left Command, Option, Control, etc.

## Uninstall

```bash
./scripts/uninstall.sh
```

## License

MIT — free to use, modify, share. See [LICENSE](LICENSE).
