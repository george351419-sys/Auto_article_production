#!/bin/bash
# Auto Content Production — uninstall script
# Usage: bash deploy/scripts/uninstall.sh
set -e

LAUNCHD_DIR="$HOME/Library/LaunchAgents"

echo "=== Auto Content Production · Uninstall ==="

for plist in "$LAUNCHD_DIR"/com.bessie.autocontent.*.plist; do
    if [ -f "$plist" ]; then
        name=$(basename "$plist")
        launchctl unload "$plist" 2>/dev/null || true
        rm -f "$plist"
        echo "  Removed: $name"
    fi
done

echo "=== Done ==="
