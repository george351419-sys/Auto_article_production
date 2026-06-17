#!/bin/bash
# Auto Content Production — install script
# Usage: bash deploy/scripts/install.sh
#
# Generates launchd plist files and installs them for the current user.
# Each module gets its own plist with KeepAlive (auto-restart on crash).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LAUNCHD_SRC="$PROJECT_DIR/deploy/launchd"

echo "=== Auto Content Production · Install ==="
echo "Project: $PROJECT_DIR"
echo "LaunchAgents: $LAUNCHD_DIR"
echo ""

# Step 1: Generate plist files
echo "[1/3] Generating plist files..."
mkdir -p "$LAUNCHD_SRC"
python3 "$SCRIPT_DIR/generate_plists.py"
echo ""

# Step 2: Unload existing services (if any)
echo "[2/3] Unloading existing services..."
for plist in "$LAUNCHD_SRC"/*.plist; do
    name=$(basename "$plist")
    dest="$LAUNCHD_DIR/$name"
    if [ -f "$dest" ]; then
        launchctl unload "$dest" 2>/dev/null || true
        echo "  Unloaded: $name"
    fi
done
echo ""

# Step 3: Copy and load
echo "[3/3] Installing and loading services..."
mkdir -p "$LAUNCHD_DIR"
for plist in "$LAUNCHD_SRC"/*.plist; do
    name=$(basename "$plist")
    dest="$LAUNCHD_DIR/$name"
    cp "$plist" "$dest"
    launchctl load "$dest" 2>/dev/null || true
    echo "  Installed: $name"
done
echo ""

echo "=== Done ==="
echo "Check status:  launchctl list | grep com.bessie.autocontent"
echo "Uninstall:     bash deploy/scripts/uninstall.sh"
