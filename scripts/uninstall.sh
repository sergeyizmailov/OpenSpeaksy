#!/usr/bin/env bash
#
# OpenSpeaksy uninstaller.
#
# Stops and removes LaunchAgents and logs. Leaves the project directory and
# whisper.cpp build alone — delete them manually if you want.

set -euo pipefail

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LABEL_APP="com.openspeaksy"
LABEL_WHISPER="com.openspeaksy.whisper"

echo "==> Unloading LaunchAgents"
launchctl unload "$LAUNCH_AGENTS/${LABEL_APP}.plist"     2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS/${LABEL_WHISPER}.plist" 2>/dev/null || true

echo "==> Removing LaunchAgent plists"
rm -f "$LAUNCH_AGENTS/${LABEL_APP}.plist" "$LAUNCH_AGENTS/${LABEL_WHISPER}.plist"

echo "==> Cleaning logs"
rm -f /tmp/openspeaksy.log /tmp/openspeaksy-whisper.log
rm -rf "$HOME/Library/Logs/com.openspeaksy"

cat <<EOF

✓ OpenSpeaksy uninstalled.

The project directory, the Python venvs, whisper.cpp, and the .pending/ queue
were left intact. Remove them manually if you no longer need them:

    rm -rf "$(cd "$(dirname "$0")/.." && pwd)"

You may also want to revoke Input Monitoring / Accessibility permissions in
System Settings → Privacy & Security.
EOF
