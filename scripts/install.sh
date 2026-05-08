#!/usr/bin/env bash
#
# OpenSpeaksy installer for macOS.
#
# Sets up the Python venv and the LaunchAgent that runs main.py.
# Asks for a Groq API key and writes it into the plist's EnvironmentVariables.
# Get a free key at https://console.groq.com/keys.
#
# Usage:   ./scripts/install.sh
# Env:     PYTHON_RUNTIME=python3.13
#          GROQ_API_KEYS=key1,key2  (skip the interactive prompt)

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

# --- Groq API key -----------------------------------------------------------

step "Configuring Groq API key"
if [[ -z "${GROQ_API_KEYS:-}" ]]; then
    cat <<EOF
    OpenSpeaksy uses the Groq cloud Whisper API for transcription.
    Get a free API key at: https://console.groq.com/keys

    The key is written only into your local plist
    ($LAUNCH_AGENTS/${LABEL_APP}.plist) — never to this repo.
    For multiple keys with rotation, paste them comma-separated.

EOF
    read -r -p "    Paste your Groq API key(s): " GROQ_API_KEYS
fi
[[ -n "$GROQ_API_KEYS" ]] || fail "no Groq API key provided"

# --- main app venv ----------------------------------------------------------

step "Creating Python venv for the app"
"$PYTHON_RUNTIME" -m venv venv
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
"$PYTHON_RUNTIME" - "$PROJECT_ROOT/launchd/${LABEL_APP}.plist.template" \
                    "$LAUNCH_AGENTS/${LABEL_APP}.plist" \
                    "$PROJECT_ROOT" \
                    "$GROQ_API_KEYS" <<'PYEOF'
import os, sys, plistlib
template, target, project_root, groq_keys = sys.argv[1:5]
with open(template, "rb") as f:
    pl = plistlib.load(f)

def replace(node):
    if isinstance(node, list):
        return [replace(x) for x in node]
    if isinstance(node, dict):
        return {k: replace(v) for k, v in node.items()}
    if isinstance(node, str):
        return node.replace("__PROJECT_ROOT__", project_root).replace("__GROQ_API_KEYS__", groq_keys)
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

  Hold right Command, speak, release. The transcription is pasted into the
  focused field and stays in the clipboard.

  Logs:    tail -f ~/Library/Logs/com.openspeaksy/main.log
  Stop:    launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
  Remove:  ./scripts/uninstall.sh

To rotate the API key later, edit
$LAUNCH_AGENTS/${LABEL_APP}.plist
and re-run: launchctl unload ... && launchctl load ...
EOF
