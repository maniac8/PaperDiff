#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/paperdiff"
python3 launch_desktop.py --daemon
# Close the launcher Terminal window cleanly if invoked via Finder double-click
if [ -n "$TERM_PROGRAM" ] && [ "$TERM_PROGRAM" = "Apple_Terminal" ]; then
  osascript -e 'tell application "Terminal" to close (every window whose frontmost is true)' >/dev/null 2>&1 &
fi
exit 0
