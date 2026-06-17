"""Main entry point for the topic selection system.

Usage:
    python main.py                # Start server with defaults (127.0.0.1:8766)
    python main.py --port 8080    # Custom port
    python main.py --host 0.0.0.0 # Bind to all interfaces
"""
import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from config import load_config


def _setup_logging():
    log_dir = Path("data")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "server.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def main():
    _setup_logging()
    config = load_config()

    parser = argparse.ArgumentParser(description="选题系统 · Topic Selection System")
    parser.add_argument("--host", default=config["server_host"], help="Server host")
    parser.add_argument("--port", type=int, default=config["server_port"], help="Server port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    print(f"选题系统 v1.0.0")
    print(f"  启动地址: http://{args.host}:{args.port}")
    print(f"  API 文档: http://{args.host}:{args.port}/docs")
    print()

    uvicorn.run(
        "server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
