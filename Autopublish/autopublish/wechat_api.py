"""WeChat Official Account API publisher with full Markdown-to-HTML conversion and automatic image upload to WeChat CDN.
See the publish() method for the main entry point.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import urllib.error
from typing import Any

from autopublish.base import PublishResult, PublishStatus

WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"
WECHAT_STABLE_TOKEN_URL = f"{WECHAT_API_BASE}/stable_token"
WECHAT_DRAFT_ADD_URL = f"{WECHAT_API_BASE}/draft/add"
WECHAT_FREEPUBLISH_SUBMIT_URL = f"{WECHAT_API_BASE}/freepublish/submit"
WECHAT_MATERIAL_ADD_URL = f"{WECHAT_API_BASE}/material/add_material"
WECHAT_MEDIA_UPLOADIMG_URL = f"{WECHAT_API_BASE}/media/uploadimg"

MAX_COVER_SIZE = 10 * 1024 * 1024
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_IMAGE_COUNT = 9


class WechatApiPublisher:
    """Publish articles to 公众号 via API with Markdown-to-HTML conversion.

    The publish() method accepts Markdown body with ![alt](url) image markers
    and converts them to proper HTML with images uploaded to WeChat CDN.
    """

    def __init__(self, platform="wechat_official", app_id="", app_secret=""):
        self.platform = platform
        self.app_id = app_id
        self.app_secret = app_secret
        self._access_token = ""
        self._token_expires_at = 0.0

    @classmethod
    def from_accounts_json(cls):
        from pathlib import Path
        dp = Path(__file__).resolve().parent.parent / ".data" / "accounts.json"
        if not dp.exists():
            raise ValueError(f"accounts.json not found at {dp}")
        accts = json.loads(dp.read_text(encoding="utf-8"))
        wc = accts.get("wechat_official", {})
        raw = (wc.get("cookie") or "").strip()
        if not raw:
            raise ValueError("公众号未配置 AppID/AppSecret")
        aid = ""
        sec = ""
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("AppID="):
                aid = line.split("=", 1)[1]
            elif line.startswith("AppSecret="):
                sec = line.split("=", 1)[1]
        if not aid or not sec:
            raise ValueError("请配置 AppID 和 AppSecret")
        return cls(app_id=aid, app_secret=sec)

    def _get_access_token(self):
        if self._access_token and time.time() < self._token_expires_at - 120:
            return self._access_token
        req = urllib.request.Request(
            WECHAT_STABLE_TOKEN_URL,
            data=json.dumps({"grant_type": "client_credential", "appid": self.app_id, "app_secret": self.app_secret, "force_refresh": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"token failed (HTTP {e.code}): {body[:300]}")
        except Exception as e:
            raise RuntimeError(f"token network error: {e}")
        token = data.get("access_token", "")
        if not token:
            errcode = data.get("errcode", "")
            errmsg = data.get("errmsg", "")
            raise RuntimeError(f"token failed: errcode={errcode} errmsg={errmsg}")
        expires = data.get("expires_in", 7200)
        self._access_token = token
        self._token_expires_at = time.time() + expires
        return token

    def _api_post(self, url, payload):
        for _ in range(2):
            token = self._get_access_token()
            full_url = f"{url}{'&' if '?' in url else '?'}access_token={token}"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(full_url, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8", errors="replace")
                try:
                    result = json.loads(error_body)
                except json.JSONDecodeError:
                    result = {"errcode": e.code, "errmsg": error_body[:200]}
            if result.get("errcode") == 40001:
                self._access_token = ""
                continue
            return result
        return result

    def _upload_thumb(self, cover_path):
        if not cover_path:
            return ""
        return self._upload_permanent_material(cover_path, "image")

    def _upload_permanent_material(self, file_path, media_type):
        import mimetypes
        from pathlib import Path
        path = Path(file_path)
        if not path.exists():
            return ""
        file_size = path.stat().st_size
        if media_type == "image" and file_size > MAX_COVER_SIZE:
            return ""
        mime = mimetypes.guess_type(file_path)[0] or "image/png"
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        file_bytes = path.read_bytes()
        bl = [f"--{boundary}", f'Content-Disposition: form-data; name="media"; filename="{path.name}"', f"Content-Type: {mime}", ""]
        header = "\r\n".join(bl).encode("utf-8") + b"\r\n"
        footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        data = header + file_bytes + footer
        token = self._get_access_token()
        full_url = f"{WECHAT_MATERIAL_ADD_URL}?access_token={token}&type={media_type}"
        req = urllib.request.Request(full_url, data=data, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            result = json.loads(e.read().decode("utf-8", errors="replace"))
        media_id = result.get("media_id", "")
        return media_id

    def _upload_content_image(self, image_path):
        import mimetypes
        from pathlib import Path
        path = Path(image_path)
        if not path.exists():
            return ""
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        bl = [f"--{boundary}", f'Content-Disposition: form-data; name="media"; filename="{path.name}"', f"Content-Type: {mime}", ""]
        header = "\r\n".join(bl).encode("utf-8") + b"\r\n"
        footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        data = header + path.read_bytes() + footer
        token = self._get_access_token()
        full_url = f"{WECHAT_MEDIA_UPLOADIMG_URL}?access_token={token}"
        req = urllib.request.Request(full_url, data=data, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            result = json.loads(e.read().decode("utf-8", errors="replace"))
        url = result.get("url", "")
        return url

    # ── Markdown → HTML conversion ──────────────────────────

    def _markdown_body_to_html(self, body):
        """Convert Markdown body with image markers to HTML.

        Handles:
        - ![alt](prompt://xxx) → stripped (no real image)
        - ![alt](http://...) → download → upload to WeChat CDN → <img>
        - ![alt](local-path) → upload to WeChat CDN → <img>
        - ## / ### headings → <h2>/<h3>
        - **bold** → <strong>
        - Paragraphs → <p> with <br> for single newlines
        """
        import tempfile
        from pathlib import Path

        replacements = {}

        def _resolve(url):
            if url in replacements:
                return replacements[url]
            if url.startswith("prompt://"):
                replacements[url] = ""
                return ""
            if Path(url).exists():
                cdn = self._upload_content_image(url)
                replacements[url] = cdn
                return cdn
            if url.startswith("http://") or url.startswith("https://"):
                tmp = None
                try:
                    resp = urllib.request.urlopen(url, timeout=15)
                    ct = resp.headers.get("Content-Type", "")
                    sfx = ".jpg"
                    if "png" in ct:
                        sfx = ".png"
                    elif "webp" in ct:
                        sfx = ".webp"
                    elif "gif" in ct:
                        sfx = ".gif"
                    fd, tmp = tempfile.mkstemp(suffix=sfx)
                    with os.fdopen(fd, "wb") as fp:
                        fp.write(resp.read())
                    cdn = self._upload_content_image(tmp)
                    replacements[url] = cdn
                    return cdn
                except Exception as e:
                    print(f"[WechatAPI] Failed to process {url}: {e}")
                    return ""
                finally:
                    if tmp:
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
            return ""

        def _repl(m):
            alt = m.group(1) or ""
            url = m.group(2) or ""
            cdn = _resolve(url)
            if cdn:
                return f'<img src="{cdn}" alt="{alt}" />'
            return ""

        body = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _repl, body)
        body = re.sub(r"^### (.+)$", r"<h3>\1</h3>", body, flags=re.MULTILINE)
        body = re.sub(r"^## (.+)$", r"<h2>\1</h2>", body, flags=re.MULTILINE)
        body = re.sub(r"^# (.+)$", r"<h1>\1</h1>", body, flags=re.MULTILINE)
        body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
        body = re.sub(r"_(.+?)_", r"<em>\1</em>", body)

        paras = []
        for block in body.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            if block.startswith("<"):
                paras.append(block)
            else:
                block = block.replace("\n", "<br>")
                paras.append(f"<p>{block}</p>")
        html = "\n".join(paras)

        def _inline_raw(m):
            raw_url = m.group(1)
            cdn = _resolve(raw_url)
            if cdn:
                return f'<img src="{cdn}" />'
            return raw_url

        html = re.sub(
            r'(?<!src=")(https?://[^\s<>"\']+(?:png|jpg|jpeg|gif|webp|bmp))',
            _inline_raw, html, flags=re.IGNORECASE,
        )

        return html

    # ── Main publish flow ─────────────────────────────────

    def publish(
        self,
        title,
        body,
        summary="",
        tags=None,
        cover_path="",
        image_paths=None,
        account_name="",
        author="",
        location="",
        topic_title="",
        keywords=None,
    ):
        """Publish article via WeChat API.

        Body is expected in Markdown with ![alt](url) image markers.
        This method converts Markdown to HTML, downloads remote images,
        uploads them to WeChat CDN, and replaces the markers.

        Flow:
        1. Upload cover image → thumb_media_id
        2. Convert Markdown body to HTML + upload inline images
        3. Create draft
        4. Free-publish the draft
        """
        try:
            if not cover_path:
                return PublishResult(status="failed", error_message="封面图为必填项")
            thumb_id = self._upload_thumb(cover_path)
            if not thumb_id:
                return PublishResult(status="failed", error_message=f"封面图上传失败: {cover_path}")

            body_html = self._markdown_body_to_html(body)

            digest = (summary or body_html[:120]).replace(chr(34), chr(39)).replace("\n", " ")[:120]
            article = {"title": title[:64], "content": body_html, "digest": digest, "thumb_media_id": thumb_id}
            if author:
                article["author"] = author[:8]
            result = self._api_post(WECHAT_DRAFT_ADD_URL, {"articles": [article]})
            errcode = result.get("errcode", 0)
            media_id = result.get("media_id", "")
            if errcode != 0 or not media_id:
                return PublishResult(status="failed", error_message=f"草稿创建失败: errcode={errcode} errmsg={result.get('errmsg','')}")
            print(f"[WechatAPI] Draft created: media_id={media_id}")
            pub = self._api_post(WECHAT_FREEPUBLISH_SUBMIT_URL, {"media_id": media_id})
            pub_errcode = pub.get("errcode", 0)
            if pub_errcode != 0:
                return PublishResult(status="failed", error_message=f"发布失败: errcode={pub_errcode} errmsg={pub.get('errmsg','')}")
            print(f"[WechatAPI] Published: {pub}")
            return PublishResult(status="success", platform_url="https://mp.weixin.qq.com/")
        except RuntimeError as e:
            return PublishResult(status="failed", error_message=str(e))
        except Exception as e:
            return PublishResult(status="failed", error_message=f"WechatAPI 异常: {e}")
