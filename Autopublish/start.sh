#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

# ── 1. Create virtual environment if not exists ─────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "[autopublish] 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

# ── 2. Activate ─────────────────────────────────────────────
source "$VENV_DIR/bin/activate"

# ── 3. Install/upgrade dependencies ─────────────────────────
echo "[autopublish] 检查依赖..."
pip install -q --upgrade pip
pip install -q playwright

# ── 4. Install Chromium if not already ──────────────────────
if ! playwright install chromium --dry-run 2>/dev/null; then
    echo "[autopublish] 安装 Chromium 浏览器（首次约 150MB）..."
    playwright install chromium
fi

# ── 5. Ensure config files exist ────────────────────────────
mkdir -p "$PROJECT_DIR/.data"
mkdir -p "$PROJECT_DIR/.cookies"

# ── 6. Launch server ────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   AutoPublish 多平台自动发布系统              ║"
echo "  ║   打开 → http://localhost:8765               ║"
echo "  ║   按 Ctrl+C 停止                             ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

python3 "$PROJECT_DIR/server.py"
