#!/usr/bin/env bash
#
# OpenSpeaksy installer for macOS.
#
# Builds whisper.cpp with Core ML, downloads the Whisper model, generates the
# ANE-accelerated encoder, sets up the Python venv, installs LaunchAgents.
#
# Usage:   ./scripts/install.sh
# Env:     WHISPER_MODEL=large-v3   (or large-v3-turbo, medium, etc.)
#          PYTHON_RUNTIME=python3.13
#          PYTHON_COREML=python3.11

set -euo pipefail

# --- config -----------------------------------------------------------------

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LABEL_APP="com.openspeaksy"
LABEL_WHISPER="com.openspeaksy.whisper"

WHISPER_MODEL="${WHISPER_MODEL:-large-v3}"
# Pin whisper.cpp to a known-good commit so installs are reproducible. Override
# with WHISPER_CPP_REF=master to track upstream HEAD if you know what you want.
WHISPER_CPP_REF="${WHISPER_CPP_REF:-v1.7.5}"
PYTHON_RUNTIME="${PYTHON_RUNTIME:-python3.13}"
PYTHON_COREML="${PYTHON_COREML:-python3.11}"

cd "$PROJECT_ROOT"

# --- helpers ----------------------------------------------------------------

step()  { printf "\n\033[1;36m==>\033[0m %s\n" "$1"; }
note()  { printf "    %s\n" "$1"; }
fail()  { printf "\n\033[1;31m✗\033[0m %s\n" "$1" >&2; exit 1; }

# --- preflight --------------------------------------------------------------

step "Checking platform"
[[ "$(uname -s)" == "Darwin" ]] || fail "macOS only"
arch="$(uname -m)"
if [[ "$arch" != "arm64" ]]; then
    note "WARNING: not Apple Silicon ($arch). Core ML/ANE acceleration unavailable; CPU fallback will be used."
fi

step "Checking Xcode Command Line Tools"
if ! xcode-select -p &>/dev/null; then
    note "Installing Xcode CLT (a GUI prompt will appear; rerun this script after it finishes)"
    xcode-select --install || true
    fail "Xcode CLT not installed yet — rerun once installation completes"
fi

step "Checking Homebrew"
if ! command -v brew &>/dev/null; then
    note "Installing Homebrew"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi

step "Ensuring Python interpreters"
command -v "$PYTHON_RUNTIME" &>/dev/null || brew install "${PYTHON_RUNTIME/python/python@}"
command -v "$PYTHON_COREML"  &>/dev/null || brew install "${PYTHON_COREML/python/python@}"

step "Ensuring CMake"
command -v cmake &>/dev/null || brew install cmake

# --- whisper.cpp ------------------------------------------------------------

step "Cloning whisper.cpp @ $WHISPER_CPP_REF"
if [[ ! -d whisper.cpp ]]; then
    git clone https://github.com/ggml-org/whisper.cpp.git
fi

# Always pin to the requested ref — idempotent across reinstalls.
# Refuses to switch if the working tree is dirty so we don't lose user changes.
(
    cd whisper.cpp
    if [[ -n "$(git status --porcelain)" ]]; then
        note "whisper.cpp working tree is dirty — leaving it alone. Stash or reset to pin to $WHISPER_CPP_REF."
    else
        git fetch --tags --quiet origin
        git checkout --quiet "$WHISPER_CPP_REF"
    fi
)

step "Downloading Whisper model: $WHISPER_MODEL"
if [[ ! -f "whisper.cpp/models/ggml-${WHISPER_MODEL}.bin" ]]; then
    (cd whisper.cpp && bash models/download-ggml-model.sh "$WHISPER_MODEL")
fi

step "Building whisper.cpp with Core ML"
(cd whisper.cpp && cmake -B build -DWHISPER_COREML=1 -DWHISPER_COREML_ALLOW_FALLBACK=1 >/dev/null)
(cd whisper.cpp && cmake --build build --config Release -j)

if [[ "$arch" == "arm64" && ! -d "whisper.cpp/models/ggml-${WHISPER_MODEL}-encoder.mlmodelc" ]]; then
    step "Generating Core ML encoder (one-time, takes 5-10 min on first run)"
    "$PYTHON_COREML" -m venv venv-coreml
    source venv-coreml/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r whisper.cpp/models/requirements-coreml.txt
    (cd whisper.cpp && bash models/generate-coreml-model.sh "$WHISPER_MODEL")
    deactivate
    note "Core ML encoder built. You can delete venv-coreml/ to free ~900 MB if you don't plan to switch models."
fi

# --- main app venv ----------------------------------------------------------

step "Creating Python venv for the app"
"$PYTHON_RUNTIME" -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
deactivate

# --- LaunchAgents -----------------------------------------------------------

step "Generating LaunchAgent plists"
mkdir -p "$LAUNCH_AGENTS"
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g; s|__MODEL__|$WHISPER_MODEL|g" \
    "$PROJECT_ROOT/launchd/${LABEL_APP}.plist.template" \
    > "$LAUNCH_AGENTS/${LABEL_APP}.plist"
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g; s|__MODEL__|$WHISPER_MODEL|g" \
    "$PROJECT_ROOT/launchd/${LABEL_WHISPER}.plist.template" \
    > "$LAUNCH_AGENTS/${LABEL_WHISPER}.plist"

step "Loading LaunchAgents"
launchctl unload "$LAUNCH_AGENTS/${LABEL_WHISPER}.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS/${LABEL_APP}.plist"     2>/dev/null || true
launchctl load   "$LAUNCH_AGENTS/${LABEL_WHISPER}.plist"
launchctl load   "$LAUNCH_AGENTS/${LABEL_APP}.plist"

# --- finish -----------------------------------------------------------------

printf "\n\033[1;32m✓ OpenSpeaksy installed.\033[0m\n\n"
cat <<EOF
The first whisper-server start compiles the Core ML encoder for your chip.
This takes 2-5 minutes — you'll see "Core ML model loaded" in the log when ready:

    tail -f /tmp/openspeaksy-whisper.log

Next: grant macOS permissions

System Settings → Privacy & Security:

  • Input Monitoring  → enable for: $PROJECT_ROOT/venv/bin/python
  • Accessibility     → enable the same binary
  • Microphone        → it'll prompt you on first recording; allow

Using it

  Hold right Command, speak, release. Transcription is pasted into the focused field
  and stays in the clipboard.

  Logs:    tail -f ~/Library/Logs/com.openspeaksy/main.log
  Stop:    launchctl unload ~/Library/LaunchAgents/com.openspeaksy.plist
  Remove:  ./scripts/uninstall.sh
EOF
