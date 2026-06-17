"""Bridge to social-auto-upload CLI tool.

social-auto-upload (https://github.com/dreammis/social-auto-upload) is an
external Python tool that automates publishing to Chinese social platforms.
This module generates the tool's input config and calls it as a subprocess.

Requires social-auto-upload to be installed and available in PATH, or at the
path specified by SOCIAL_AUTO_UPLOAD_PATH env var.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any

from autopublish.base import PublishResult, PublishStatus


class SocialAutoUploadPublisher:
    """Bridge to social-auto-upload.

    Generates config JSON and calls the tool as a subprocess.
    """

    PLATFORM_MAP = {
        "wechat_official": "wechat",
        "xiaohongshu": "xiaohongshu",
        "toutiao": "toutiao",
    }

    def __init__(self, platform: str):
        self.platform = platform
        self.tool_platform = self.PLATFORM_MAP.get(platform, platform)
        self.tool_path = self._resolve_tool_path()

    def _resolve_tool_path(self) -> str:
        env_path = os.getenv("SOCIAL_AUTO_UPLOAD_PATH")
        if env_path:
            return env_path
        candidates = [
            "social-auto-upload",
            "social-auto-upload/main.py",
            "./social-auto-upload/main.py",
            "../social-auto-upload/main.py",
        ]
        for candidate in candidates:
            try:
                result = subprocess.run(
                    ["which", candidate.split("/")[0]],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return candidate
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return "social-auto-upload"

    def _generate_config(self, publish_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "accounts": {
                self.tool_platform: {
                    "cookie": publish_data.get("cookie", ""),
                    "enable": True,
                }
            },
            "contents": [
                {
                    "platform": self.tool_platform,
                    "title": publish_data.get("title", ""),
                    "text": publish_data.get("body", ""),
                    "summary": publish_data.get("summary", ""),
                    "tags": publish_data.get("tags", []),
                    "images": publish_data.get("image_paths", []),
                    "link": publish_data.get("link", ""),
                    "publish_type": publish_data.get("publish_type", "article"),
                }
            ],
        }

    def publish(
        self,
        title: str,
        body: str,
        summary: str = "",
        tags: list[str] | None = None,
        cover_path: str = "",
        image_paths: list[str] | None = None,
        account_name: str = "",
        cookie: str = "",
    ) -> PublishResult:
        if not self.tool_path:
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message="social-auto-upload not found.",
            )

        publish_data = {
            "title": title,
            "body": body,
            "summary": summary,
            "tags": tags or [],
            "image_paths": image_paths or [],
            "cover_path": cover_path,
            "cookie": cookie,
            "account_name": account_name,
        }

        config = self._generate_config(publish_data)

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                config_path = f.name

            result = subprocess.run(
                ["python", self.tool_path, self.tool_platform, config_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            os.unlink(config_path)

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                url = ""
                for line in stdout.split("\n"):
                    if "http" in line and (".com" in line or ".cn" in line):
                        url = line.strip()
                        break
                return PublishResult(
                    status=PublishStatus.SUCCESS,
                    platform_url=url or f"https://{self.platform}.example.com/published",
                )
            else:
                return PublishResult(
                    status=PublishStatus.FAILED,
                    error_message=f"social-auto-upload failed: {stderr[:200] or stdout[:200]}",
                )

        except FileNotFoundError:
            return PublishResult(status=PublishStatus.FAILED, error_message="Python not found.")
        except subprocess.TimeoutExpired:
            return PublishResult(status=PublishStatus.FAILED, error_message="social-auto-upload timed out after 120s")
        except Exception as exc:
            return PublishResult(status=PublishStatus.FAILED, error_message=str(exc))
