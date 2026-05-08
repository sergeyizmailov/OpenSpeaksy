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

**Step 2.** Open Terminal and run:

```bash
git clone https://github.com/sergeyizmailov/OpenSpeaksy.git ~/OpenSpeaksy
cd ~/OpenSpeaksy
./scripts/install.sh
```

When it asks for your key, paste it and press Enter.

**Step 3.** Mac will need permission to listen to your keyboard and paste text. Open **System Settings → Privacy & Security**, and turn on:
- **Input Monitoring** — for `python` (you'll see the file in the list)
- **Accessibility** — same `python`

That's it. Hold right Command, talk, let go.

> Don't have Terminal experience? Open **Claude**, **ChatGPT**, **Cursor**, or any AI assistant, paste this and it'll do everything for you:
>
> > Install OpenSpeaksy from <https://github.com/sergeyizmailov/OpenSpeaksy>. I have a Groq API key ready. Walk me through giving it the macOS permissions.

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
