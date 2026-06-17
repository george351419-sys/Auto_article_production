#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Install deps if needed
if ! python3 -c "import fastapi, aiosqlite, apscheduler, httpx" 2>/dev/null; then
  echo "Installing orchestrator dependencies..."
  pip3 install -r requirements.txt -q
fi

# Apply any pending DB migrations before the server starts (also runs on
# lifespan startup, but doing it here gives a clean exit code if migrations
# are broken so the launcher doesn't loop on a half-init schema).
python3 -m orchestrator.migrate data/pipeline.db || {
  echo "Migration failed — refusing to start." >&2
  exit 1
}

echo "▶ Starting orchestrator v2 on http://127.0.0.1:8800"
echo
echo "   其他模块（各自独立运行）："
echo "   distilled_characters:  cd ../distilled_characters && python3 main.py --port 8767"
echo "   select_topic:          cd ../select_topic && python3 -m uvicorn server.app:app --port 8766"
echo "   writing:               cd ../writing && npm run dev"
echo "   platform_scorer:       cd ../platform_scorer && python3 server.py"
echo "   Autopublish:           cd ../Autopublish && python3 server.py"
echo

exec python3 server_v2.py
