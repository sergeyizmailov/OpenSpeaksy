#!/usr/bin/env bash
#
# OpenSpeaksy installer for macOS.
#
# Sets up the Python venv and the LaunchAgent that runs main.py.
# Requires Gemini and Mistral API keys and writes them into the plist's
# EnvironmentVariables. Gemini 3.5 Transcribe handles all speech-to-text and
# Mistral Medium handles the translate hotkeys.
#
# Usage:   ./scripts/install.sh
# Env:     PYTHON_RUNTIME=python3.13
#          MISTRAL_API_KEY=key      (skip the Mistral prompt)
#          GEMINI_API_KEYS=key1,key2   (one or more, comma-separated)

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
    OpenSpeaksy uses Mistral Medium for Russian-to-English and
    Russian-to-Polish translation.
    Create an API key at: https://console.mistral.ai/api-keys

    The key is written only into your local plist
    ($LAUNCH_AGENTS/${LABEL_APP}.plist) — never to this repo.

EOF
    read -rs -p "    Paste your Mistral API key: " MISTRAL_API_KEY
    echo
fi
[[ -n "$MISTRAL_API_KEY" ]] || fail "no Mistral API key provided"
note "Got Mistral key ending in ...${MISTRAL_API_KEY: -4}"

step "Configuring Gemini API key(s)"
if [[ -z "${GEMINI_API_KEYS:-}" ]]; then
    cat <<EOF
    OpenSpeaksy uses Gemini 3.5 Transcribe for speech-to-text.
    Create an API key at: https://aistudio.google.com/apikey

    The free tier allows 3 requests per minute PER PROJECT, so you can paste
    several comma-separated keys from different Google projects to raise that
    ceiling — each key carries its own quota.

    The key is written only into your local plist
    ($LAUNCH_AGENTS/${LABEL_APP}.plist) — never to this repo.

EOF
    read -rs -p "    Paste your Gemini API key(s), comma-separated: " GEMINI_API_KEYS
    echo
fi
[[ -n "$GEMINI_API_KEYS" ]] || fail "no Gemini API key provided"
note "Got $(printf '%s' "$GEMINI_API_KEYS" | awk -F, '{print NF}') Gemini key(s)"

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
MISTRAL_API_KEY="$MISTRAL_API_KEY" GEMINI_API_KEYS="$GEMINI_API_KEYS" \
"$PYTHON_RUNTIME" - "$PROJECT_ROOT/launchd/${LABEL_APP}.plist.template" \
                    "$LAUNCH_AGENTS/${LABEL_APP}.plist" \
                    "$PROJECT_ROOT" <<'PYEOF'
import os, sys, plistlib
template, target, project_root = sys.argv[1:4]
mistral_key = os.environ.pop("MISTRAL_API_KEY")
gemini_keys = os.environ.pop("GEMINI_API_KEYS")
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
                    .replace("__GEMINI_API_KEYS__", gemini_keys))
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

  Hold right Command, speak, release — dictate in any supported language;
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
