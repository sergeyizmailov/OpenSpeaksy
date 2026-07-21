#!/usr/bin/env bash
#
# OpenSpeaksy installer for macOS.
#
# Sets up the Python venv and the LaunchAgent that runs main.py.
# Requires one Mistral API key and optionally accepts an ElevenLabs key, then
# writes them into the plist's EnvironmentVariables. Mistral Voxtral handles
# transcription, Mistral Medium handles translations, and ElevenLabs remains a
# selectable speech-to-text fallback.
#
# Usage:   ./scripts/install.sh
# Env:     PYTHON_RUNTIME=python3.13
#          MISTRAL_API_KEY=key      (skip the Mistral prompt)
#          ELEVENLABS_API_KEY=key   (optional retained fallback)

set -euo pipefail

# --- config -----------------------------------------------------------------

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LABEL_APP="com.openspeaksy"

PYTHON_RUNTIME="${PYTHON_RUNTIME:-python3.13}"

cd "$PROJECT_ROOT"

# --- helpers ----------------------------------------------------------------

step()  { printf "\n\033[1;36m==>\033[0m %s\n" "$1"; }
note()  { printf "    %s\n" "$1"; }
fail()  { printf "\n\033[1;31m✗\033[0m %s\n" "$1" >&2; exit 1; }

# --- preflight --------------------------------------------------------------

step "Checking platform"
[[ "$(uname -s)" == "Darwin" ]] || fail "macOS only"

step "Checking Homebrew"
if ! command -v brew &>/dev/null; then
    note "Installing Homebrew"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi

step "Ensuring Python interpreter"
command -v "$PYTHON_RUNTIME" &>/dev/null || brew install "${PYTHON_RUNTIME/python/python@}"
# A freshly installed keg may not be on PATH yet (new shell hasn't sourced
# brew shellenv) — fall back to the absolute keg path.
if ! command -v "$PYTHON_RUNTIME" &>/dev/null; then
    PYTHON_RUNTIME="$(brew --prefix)/bin/$PYTHON_RUNTIME"
    command -v "$PYTHON_RUNTIME" &>/dev/null || fail "Python interpreter not found after install"
fi

# --- API keys ---------------------------------------------------------------

step "Configuring Mistral API key"
if [[ -z "${MISTRAL_API_KEY:-}" ]]; then
    cat <<EOF
    OpenSpeaksy uses Mistral Voxtral Mini Transcribe 2 for speech-to-text and
    Mistral Medium for Russian-to-English and Russian-to-Polish translation.
    Create an API key at: https://console.mistral.ai/api-keys

    The key is written only into your local plist
    ($LAUNCH_AGENTS/${LABEL_APP}.plist) — never to this repo.

EOF
    read -rs -p "    Paste your Mistral API key: " MISTRAL_API_KEY
    echo
fi
[[ -n "$MISTRAL_API_KEY" ]] || fail "no Mistral API key provided"
note "Got Mistral key ending in ...${MISTRAL_API_KEY: -4}"

step "Configuring optional ElevenLabs fallback"
if [[ -z "${ELEVENLABS_API_KEY:-}" ]]; then
    cat <<EOF
    ElevenLabs Scribe v2 can be retained as a fallback speech-to-text backend.
    Create an API key at: https://elevenlabs.io/app/developers/api-keys

    The key is written only into your local plist
    ($LAUNCH_AGENTS/${LABEL_APP}.plist) — never to this repo.

EOF
    read -rs -p "    Paste an ElevenLabs API key, or press Enter to skip: " ELEVENLABS_API_KEY
    echo
fi
if [[ -n "$ELEVENLABS_API_KEY" ]]; then
    note "Got ElevenLabs key ending in ...${ELEVENLABS_API_KEY: -4}"
else
    note "ElevenLabs fallback not configured"
fi

# --- main app venv ----------------------------------------------------------

step "Creating Python venv for the app"
# --clear rebuilds a stale venv left by a previous install (e.g. after a
# Homebrew Python upgrade broke the interpreter symlinks).
"$PYTHON_RUNTIME" -m venv --clear venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
deactivate

# --- LaunchAgent ------------------------------------------------------------

step "Generating LaunchAgent plist"
mkdir -p "$LAUNCH_AGENTS"

# Use Python's plistlib so paths and key values with XML-sensitive characters
# are escaped correctly — sed-substitution would corrupt the plist.
MISTRAL_API_KEY="$MISTRAL_API_KEY" ELEVENLABS_API_KEY="$ELEVENLABS_API_KEY" \
"$PYTHON_RUNTIME" - "$PROJECT_ROOT/launchd/${LABEL_APP}.plist.template" \
                    "$LAUNCH_AGENTS/${LABEL_APP}.plist" \
                    "$PROJECT_ROOT" <<'PYEOF'
import os, sys, plistlib
template, target, project_root = sys.argv[1:4]
mistral_key = os.environ.pop("MISTRAL_API_KEY")
elevenlabs_key = os.environ.pop("ELEVENLABS_API_KEY")
with open(template, "rb") as f:
    pl = plistlib.load(f)

def replace(node):
    if isinstance(node, list):
        return [replace(x) for x in node]
    if isinstance(node, dict):
        return {k: replace(v) for k, v in node.items()}
    if isinstance(node, str):
        return (node.replace("__PROJECT_ROOT__", project_root)
                    .replace("__MISTRAL_API_KEY__", mistral_key)
                    .replace("__ELEVENLABS_API_KEY__", elevenlabs_key))
    return node

# Open with 0600 from the start so the API key is never world-readable,
# even briefly. os.open + plistlib.dump on the resulting fd avoids the
# default-umask window an open(target, "wb") + os.chmod sequence leaves.
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "wb") as f:
    plistlib.dump(replace(pl), f)
# os.open honors mode only on file creation; chmod fixes a pre-existing target.
os.chmod(target, 0o600)
PYEOF

step "Loading LaunchAgent"
launchctl unload "$LAUNCH_AGENTS/${LABEL_APP}.plist" 2>/dev/null || true
launchctl load   "$LAUNCH_AGENTS/${LABEL_APP}.plist"

# --- finish -----------------------------------------------------------------

printf "\n\033[1;32m✓ OpenSpeaksy installed.\033[0m\n\n"
cat <<EOF
Next: grant macOS permissions

System Settings → Privacy & Security:

  • Input Monitoring  → enable for: $PROJECT_ROOT/venv/bin/python
  • Accessibility     → enable the same binary
  • Microphone        → it'll prompt you on first recording; allow

Using it

  Hold right Command, speak, release — dictate in a Voxtral-supported language;
  the text pastes verbatim. Hold right Option instead to dictate in Russian and
  have the English translation pasted. Hold right Shift to dictate in Russian
  and have the Polish translation pasted. The output also stays in your clipboard.

  Logs:    tail -f ~/Library/Logs/com.openspeaksy/main.log
  Stop:    launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
  Remove:  ./scripts/uninstall.sh

To rotate an API key later, edit
$LAUNCH_AGENTS/${LABEL_APP}.plist
and re-run: launchctl unload ... && launchctl load ...
EOF
