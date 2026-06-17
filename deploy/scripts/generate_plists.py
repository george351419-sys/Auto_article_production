#!/usr/bin/env python3
"""Generate launchd plist files from template per LLD §7.

Produces 6 plist files under deploy/launchd/.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
DEPLOY_DIR = HERE.parent
LAUNCHD_DIR = DEPLOY_DIR / "launchd"

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bessie.autocontent.{module_name}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{entry_script}</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>{port}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{module_root}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>AUTO_CONTENT_CONFIG</key>
        <string>{project_root}/shared_config.json</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>{module_root}/logs/launchd.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{module_root}/logs/launchd.stderr.log</string>
</dict>
</plist>
"""

WRITING_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bessie.autocontent.writing</string>

    <key>ProgramArguments</key>
    <array>
        <string>{node_path}</string>
        <string>server/index.ts</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{writing_root}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PORT</key>
        <string>8788</string>
        <key>AUTO_CONTENT_CONFIG</key>
        <string>{project_root}/shared_config.json</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>{writing_root}/logs/launchd.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{writing_root}/logs/launchd.stderr.log</string>
</dict>
</plist>
"""


def generate():
    python_path = "/usr/bin/python3"
    project_root = str(PROJECT_ROOT)

    # Try to find node path for writing module
    import shutil
    node_path = shutil.which("node") or "/opt/homebrew/bin/node"

    modules = [
        {
            "module_name": "orchestrator",
            "entry_script": "server_v2.py",
            "module_root": str(PROJECT_ROOT / "orchestrator"),
            "port": "8800",
        },
        {
            "module_name": "distilled_characters",
            "entry_script": "main.py",
            "module_root": str(PROJECT_ROOT / "distilled_characters"),
            "port": "8767",
        },
        {
            "module_name": "select_topic",
            "entry_script": "main.py",
            "module_root": str(PROJECT_ROOT / "select_topic"),
            "port": "8766",
        },
        {
            "module_name": "platform_scorer",
            "entry_script": "server.py",
            "module_root": str(PROJECT_ROOT / "platform_scorer"),
            "port": "8789",
        },
        {
            "module_name": "autopublish",
            "entry_script": "server.py",
            "module_root": str(PROJECT_ROOT / "Autopublish"),
            "port": "8765",
        },
    ]

    LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)

    for mod in modules:
        # Create logs dir for each module
        logs_dir = Path(mod["module_root"]) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        plist = PLIST_TEMPLATE.format(
            python_path=python_path,
            project_root=project_root,
            **mod,
        )
        filename = f"com.bessie.autocontent.{mod['module_name']}.plist"
        (LAUNCHD_DIR / filename).write_text(plist)
        print(f"Wrote {filename}")

    # Writing module (Node.js)
    writing_root = PROJECT_ROOT / "writing"
    (writing_root / "logs").mkdir(parents=True, exist_ok=True)
    writing_plist = WRITING_PLIST_TEMPLATE.format(
        node_path=node_path,
        writing_root=str(writing_root),
        project_root=project_root,
    )
    (LAUNCHD_DIR / "com.bessie.autocontent.writing.plist").write_text(writing_plist)
    print("Wrote com.bessie.autocontent.writing.plist")

    print(f"\nGenerated {len(modules) + 1} plist files in {LAUNCHD_DIR}")


if __name__ == "__main__":
    generate()
