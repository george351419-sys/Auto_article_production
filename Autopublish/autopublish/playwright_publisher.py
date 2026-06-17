"""Browser-based publisher using Playwright.

Real browser automation for WeChat Official Account (公众号),
Xiaohongshu (小红书), and Toutiao (今日头条) posting.

Supports:
- Cookie persistence for authentication
- CDP connection to browserless (remote browser)
- Platform-specific form filling
- Sensitive word detection per platform
- Image upload
"""

from __future__ import annotations
import re

import asyncio
import json
import os
import time
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / ".data"

from autopublish.base import PublishResult, PublishStatus


class PlaywrightPublisher:
    """Publish content via browser automation using Playwright.

    Uses cookie file persistence for authentication. Cookie files are stored
    in the .cookies/ directory and are loaded/saved before/after each session.

    Usage:
        publisher = PlaywrightPublisher("xiaohongshu", headless=False)
        result = await publisher.publish(...)
    """

    PLATFORM_LOGIN_URLS = {
        "wechat_official": "https://mp.weixin.qq.com/",
        "xiaohongshu": "https://creator.xiaohongshu.com/",
        "toutiao": "https://mp.toutiao.com/",
    }

    PLATFORM_NEW_ARTICLE_URLS = {
        "wechat_official": "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=10&isNew=1",
        "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish",
        "toutiao": "https://mp.toutiao.com/profile_v4/index",  # navigate via UI from home
    }

    PLATFORM_SENSITIVE_WORDS = {
        "wechat_official": ["最", "第一", "绝对", "100%", "永久", "唯一", "顶级", "首个"],
        "xiaohongshu": ["最", "第一", "必买", "必看", "全网", "唯一", "绝对", "神器"],
        "toutiao": ["最", "第一", "震惊", "重磅", "紧急", "突发", "揭秘", "绝密"],
    }

    def __init__(self, platform: str, headless: bool = True, cookie_file: str | None = None):
        self.platform = platform
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._page = None
        self._cookie_file = cookie_file or os.getenv(
            "PLAYWRIGHT_COOKIE_FILE",
            os.path.join(os.getcwd(), ".cookies", f"{platform}_cookies.json"),
        )

    async def _ensure_browser(self, connect_url: str | None = None):
        """Lazily initialize Playwright browser."""
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()

            browser_url = connect_url or os.getenv("PLAYWRIGHT_BROWSER_URL", "")
            if browser_url:
                self._browser = await self._playwright.chromium.connect_over_cdp(browser_url)
                self._page = await self._browser.new_page(
                    viewport={"width": 1280, "height": 800},
                )
            else:
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                self._page = await self._browser.new_page(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )

            await self._load_cookies()

        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Install with: pip install playwright && playwright install chromium"
            )

    async def _load_cookies(self) -> None:
        if not self._cookie_file or not self._page:
            return
        try:
            cookie_path = Path(self._cookie_file)
            if cookie_path.exists():
                cookies = json.loads(cookie_path.read_text(encoding="utf-8"))
                await self._page.context.add_cookies(cookies)
        except Exception:
            pass

    async def _save_cookies(self) -> None:
        if not self._cookie_file or not self._page:
            return
        try:
            cookie_path = Path(self._cookie_file)
            cookie_path.parent.mkdir(parents=True, exist_ok=True)
            cookies = await self._page.context.cookies()
            cookie_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _check_sensitive_content(self, title: str, body: str) -> list[str]:
        sensitive = self.PLATFORM_SENSITIVE_WORDS.get(self.platform, [])
        found = []
        text = f"{title} {body}"
        for word in sensitive:
            if word in text:
                found.append(word)
        return found

    def _segment_body_for_xiaohongshu(self, body: str) -> list[str]:
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        segments = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < 800:
                current += ("\n\n" if current else "") + p
            else:
                if current:
                    segments.append(current)
                current = p
        if current:
            segments.append(current)
        while len(segments) < 3:
            segments.append(segments[-1] if segments else "分享一个实用的小技巧，希望对大家有帮助～")
        return segments

    async def publish(
        self,
        title: str,
        body: str,
        summary: str = "",
        tags: list[str] | None = None,
        cover_path: str = "",
        image_paths: list[str] | None = None,
        account_name: str = "",
        author: str = "",
        location: str = "",
        topic_title: str = "",
        keywords: list[str] | None = None,
    ) -> PublishResult:
        """Publish content via browser automation.

        Parameters mapped to platform fields:
        - wechat_official: title, body, cover_path (browser fallback, prefer API mode)
        - toutiao: title, body, tags, cover_path, topic_title (选题)
        - xiaohongshu: title, body, tags, image_paths, location (发布地点), topic_title (话题)
        """
        try:
            await self._ensure_browser()
        except RuntimeError as exc:
            return PublishResult(status=PublishStatus.FAILED, error_message=str(exc))

        sensitive = self._check_sensitive_content(title, body or "")
        if sensitive:
            print(f"[PlaywrightPublisher:{self.platform}] WARNING sensitive words: {sensitive}")

        print(f"[PlaywrightPublisher:{self.platform}] Publishing: {title[:40]}")
        if author:
            print(f"  author={author}, location={location}, topic={topic_title}")

        try:
            new_url = self.PLATFORM_NEW_ARTICLE_URLS.get(self.platform)
            if not new_url:
                return PublishResult(status=PublishStatus.FAILED, error_message=f"Unsupported platform: {self.platform}")

            await self._page.goto(new_url, timeout=30000, wait_until="domcontentloaded")
            current_url = self._page.url

            if "login" in current_url or "passport" in current_url:
                platform_names = {"toutiao": "今日头条", "xiaohongshu": "小红书", "wechat_official": "微信公众号"}
                name = platform_names.get(self.platform, self.platform)
                return PublishResult(
                    status=PublishStatus.FAILED,
                    error_message=f"【{name}】Cookie 已过期，请重新登录：①打开平台网站手动登录 ②按 F12 → Application → Cookies → 复制所有 Cookie ③粘贴到账号管理页面保存",
                )

            tag_list = tags or []
            img_list = image_paths or []

            if self.platform == "wechat_official":
                return await self._publish_wechat(title, body, tag_list, cover_path, img_list)
            elif self.platform == "xiaohongshu":
                return await self._publish_xiaohongshu(title, body, tag_list, img_list, location=location, topic_title=topic_title)
            elif self.platform == "toutiao":
                return await self._publish_toutiao(title, body, tag_list, cover_path, img_list, topic_title=topic_title)
            else:
                return PublishResult(status=PublishStatus.FAILED, error_message=f"Unsupported: {self.platform}")

        except Exception as exc:
            return PublishResult(status=PublishStatus.FAILED, error_message=f"Browser publishing failed: {exc}")

    async def _publish_wechat(self, title: str, body: str, tags: list[str], cover_path: str, images: list[str]) -> PublishResult:
        """Browser fallback for WeChat (prefer WechatApiPublisher via API mode instead)."""
        for sel in ['input[name="title"]', ".title-input", "#title", '[placeholder*="标题"]']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=5000)
                if el:
                    await el.fill(title)
                    break
            except Exception:
                continue

        for sel in ["#js_editor_content", ".rich-media-content", '[contenteditable="true"]']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=3000)
                if el:
                    # Strip Markdown image markers before filling plain-text editor
                    clean_body = re.sub(r'!\\[([^\\]]*)\\]\\(([^)]+)\\)', lambda m: f'[图片：{m.group(1)}]' if m.group(1) else '', body)
                    await el.fill(clean_body)
                    break
            except Exception:
                continue

        # Upload cover image first (required)
        cover_files = [p for p in [cover_path, *(images or [])] if p]
        if cover_files:
            try:
                file_input = await self._page.query_selector('input[type="file"]')
                if file_input:
                    await file_input.set_input_files(cover_files[0])
            except Exception:
                pass

        for sel in ['button:has-text("保存")', 'a:has-text("保存")', ".js_save_btn"]:
            try:
                el = await self._page.wait_for_selector(sel, timeout=3000)
                if el:
                    await el.click()
                    break
            except Exception:
                continue

        time.sleep(2)
        await self._save_cookies()
        return PublishResult(status=PublishStatus.SUCCESS, platform_url="https://mp.weixin.qq.com/")

    async def _publish_xiaohongshu(
        self,
        title: str,
        body: str,
        tags: list[str],
        images: list[str],
        location: str = "",
        topic_title: str = "",
    ) -> PublishResult:
        """Publish to 小红书 as 图文笔记 (image note).

        Requires at least one image. Flow:
        1. Click "上传图文" tab (via JS on .creator-tab elements)
        2. Upload image(s) via file input
        3. Fill title: input[placeholder*="填写标题"]
        4. Fill body: .ProseMirror via execCommand('insertText')
        5. Click "发布" button
        """
        if not images:
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message="小红书图文笔记必须提供至少一张图片（image_paths 不能为空）",
            )

        # Wait for the tab bar to fully render (XHS SPA loads asynchronously)
        try:
            await self._page.wait_for_selector(".creator-tab", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Step 1: Click "上传图文" tab — use JS to find the visible .creator-tab with correct text
        await self._page.evaluate("""() => {
            const tab = Array.from(document.querySelectorAll('.creator-tab'))
                .filter(e => {
                    const r = e.getBoundingClientRect();
                    return e.innerText.trim() === '上传图文' && r.x > 0 && r.y > 0;
                })[0];
            if (tab) tab.click();
        }""")
        await asyncio.sleep(2)

        active = await self._page.evaluate(
            "() => { const a = document.querySelector('.creator-tab.active'); return a ? a.innerText.trim() : ''; }"
        )
        if active != "上传图文":
            ss = await self._screenshot("xhs_debug.png")
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"小红书：无法切换到「上传图文」标签（当前: {active}）。截图: {ss}",
            )
        print(f"[Playwright:xiaohongshu] Active tab: {active}")

        # Step 2: Upload images via file input
        for img_path in images[:9]:
            try:
                file_input = await self._page.query_selector('input[type="file"][accept*="jpg"]')
                if not file_input:
                    file_input = await self._page.query_selector('input[type="file"]')
                if file_input:
                    await file_input.set_input_files(img_path)
                    await asyncio.sleep(2)
                    print(f"[Playwright:xiaohongshu] Uploaded: {img_path}")
            except Exception as e:
                print(f"[Playwright:xiaohongshu] Image upload error: {e}")
                continue

        await asyncio.sleep(2)  # wait for upload processing

        # Step 3: Fill title — after upload, input[placeholder*="填写标题"] appears
        title_filled = False
        for sel in ['input[placeholder*="填写标题"]', 'input[placeholder*="标题"]', 'textarea[placeholder*="标题"]']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=8000)
                if el:
                    await el.click()
                    await el.fill(title)
                    title_filled = True
                    print(f"[Playwright:xiaohongshu] Filled title via: {sel}")
                    break
            except Exception:
                continue

        if not title_filled:
            print("[Playwright:xiaohongshu] WARNING: could not fill title")

        # Step 4: Fill body via execCommand (ProseMirror same as Toutiao)
        tag_str = " ".join(f"#{t}" for t in tags[:20]) if tags else ""
        full_body = f"{body[:1800]}\n\n{tag_str}".strip() if tag_str else body[:2000]

        body_filled = False
        for sel in [".ProseMirror", ".tiptap", '[contenteditable="true"]']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=5000)
                if el:
                    await el.click()
                    await asyncio.sleep(0.5)
                    inserted = await self._page.evaluate(
                        """(text) => {
                            const editor = document.querySelector('.ProseMirror') || document.querySelector('[contenteditable=\"true\"]');
                            if (!editor) return false;
                            editor.focus();
                            document.execCommand('selectAll', false, null);
                            return document.execCommand('insertText', false, text);
                        }""",
                        full_body,
                    )
                    body_filled = bool(inserted)
                    print(f"[Playwright:xiaohongshu] Filled body via execCommand: {inserted}")
                    break
            except Exception:
                continue

        if not body_filled:
            print("[Playwright:xiaohongshu] WARNING: body may not have been filled")

        await asyncio.sleep(1)

        # Dismiss any hashtag autocomplete dropdown
        await self._page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

        # Step 5: Click "发布" button.
        # XHS renders the submit button inside <xhs-publish-btn> custom element using
        # closed shadow DOM — inaccessible via JS/querySelector. Must use mouse coordinates.
        # The "发布" button sits at ~62% from the left of xhs-publish-btn's bounding box.
        btn_box = await self._page.evaluate("""() => {
            const el = document.querySelector('xhs-publish-btn');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {x: r.x, y: r.y, w: r.width, h: r.height};
        }""")

        if not btn_box:
            ss = await self._screenshot("xhs_debug.png")
            await self._save_cookies()
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"小红书：未找到 xhs-publish-btn 元素。截图: {ss}",
            )

        # Click the right-side "发布" button (62% from left edge, vertical center)
        click_x = btn_box['x'] + btn_box['w'] * 0.62
        click_y = btn_box['y'] + btn_box['h'] * 0.5
        await self._page.mouse.click(click_x, click_y)
        print(f"[Playwright:xiaohongshu] Clicked 发布 at ({click_x:.0f}, {click_y:.0f})")
        await asyncio.sleep(5)

        current_url = self._page.url
        if "success" not in current_url:
            ss = await self._screenshot("xhs_debug.png")
            await self._save_cookies()
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"小红书：点击发布后页面未跳转到成功页（当前: {current_url}）。截图: {ss}",
            )

        print(f"[Playwright:xiaohongshu] Publish success, URL: {current_url}")
        await self._save_cookies()
        return PublishResult(status=PublishStatus.SUCCESS, platform_url=current_url or "https://creator.xiaohongshu.com/")

    async def _screenshot(self, filename: str) -> str:
        path = str(_DATA_DIR / filename)
        try:
            await self._page.screenshot(path=path, full_page=False)
        except Exception:
            pass
        return path

    async def _publish_toutiao(
        self,
        title: str,
        body: str,
        tags: list[str],
        cover_path: str,
        images: list[str],
        topic_title: str = "",
    ) -> PublishResult:
        """Publish to 今日头条.

        Navigation: home → click 文章 in sidebar (navigates directly to editor) → fill editor → 预览并发布
        """
        await asyncio.sleep(2)

        # Click 文章 in sidebar — on current Toutiao this navigates directly to the article editor
        for sel in [
            'a:has-text("文章")',
            'li:has-text("文章") > a',
            '[class*="nav"] :has-text("文章")',
            '.menu-item:has-text("文章")',
        ]:
            try:
                el = await self._page.wait_for_selector(sel, timeout=3000, state="visible")
                if el:
                    await el.click()
                    print(f"[Playwright:toutiao] Clicked 文章 nav: {sel}")
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

        # Dismiss AI assistant drawer that appears and blocks all clicks
        await self._page.evaluate("""() => {
            const wrapper = document.querySelector('.byte-drawer-wrapper');
            if (wrapper) wrapper.style.display = 'none';
            const mask = document.querySelector('.byte-drawer-mask');
            if (mask) mask.style.display = 'none';
        }""")
        await asyncio.sleep(0.5)

        # Confirm editor is open by waiting for title textarea
        editor_opened = False
        for title_sel in ['textarea[placeholder*="标题"]', '[placeholder*="标题"]', 'textarea']:
            try:
                await self._page.wait_for_selector(title_sel, timeout=5000)
                editor_opened = True
                print(f"[Playwright:toutiao] Editor confirmed via: {title_sel}")
                break
            except Exception:
                continue

        # If editor not open, try clicking 写文章 button (legacy flow)
        if not editor_opened:
            for sel in [
                'button:has-text("写文章")',
                'a:has-text("写文章")',
                'button:has-text("新建文章")',
                '[class*="create"]:has-text("文章")',
            ]:
                try:
                    el = await self._page.wait_for_selector(sel, timeout=3000, state="visible")
                    if el:
                        await el.click()
                        print(f"[Playwright:toutiao] Opened editor via: {sel}")
                        await asyncio.sleep(3)
                        break
                except Exception:
                    continue
            for title_sel in ['textarea[placeholder*="标题"]', '[placeholder*="标题"]']:
                try:
                    await self._page.wait_for_selector(title_sel, timeout=5000)
                    editor_opened = True
                    break
                except Exception:
                    continue

        if not editor_opened:
            ss = await self._screenshot("toutiao_debug.png")
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"今日头条：未能打开文章编辑器，请检查账号状态。截图: {ss}",
            )

        # Fill title — use force=True to bypass any residual overlay
        title_filled = False
        for sel in ['textarea[placeholder*="标题"]', '[placeholder*="标题"]', 'textarea']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=5000)
                if el:
                    await el.click(force=True)
                    await el.fill(title)
                    title_filled = True
                    print(f"[Playwright:toutiao] Filled title via: {sel}")
                    break
            except Exception:
                continue

        if not title_filled:
            print("[Playwright:toutiao] WARNING: could not fill title")

        # Fill body — Toutiao uses ProseMirror; keyboard.type() fails for Chinese text.
        # execCommand('insertText') is intercepted correctly by ProseMirror.
        body_filled = False
        for sel in [".ProseMirror", '.ql-editor', '[contenteditable="true"]']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=5000)
                if el:
                    await el.click(force=True)
                    await asyncio.sleep(0.5)
                    inserted = await self._page.evaluate(
                        """(text) => {
                            const editor = document.querySelector('.ProseMirror') || document.querySelector('[contenteditable=\"true\"]');
                            if (!editor) return false;
                            editor.focus();
                            document.execCommand('selectAll', false, null);
                            return document.execCommand('insertText', false, text);
                        }""",
                        body,
                    )
                    body_filled = bool(inserted)
                    print(f"[Playwright:toutiao] Filled body via execCommand: {inserted}")
                    break
            except Exception:
                continue

        if not body_filled:
            print("[Playwright:toutiao] WARNING: body may not have been filled")

        # Upload cover image
        cover_candidates = [p for p in [cover_path, *(images or [])] if p]
        if cover_candidates:
            try:
                file_input = await self._page.query_selector('input[type="file"]')
                if file_input:
                    await file_input.set_input_files(cover_candidates[0])
                    await asyncio.sleep(1)
            except Exception:
                pass

        await asyncio.sleep(1)

        # Step 1: Click "预览并发布" — this scrolls the page down to show publish settings
        # (cover image, location, ads) rather than opening a separate dialog.
        pub_btn = None
        for sel in ['button:has-text("预览并发布")', '.byte-btn-primary', 'button:has-text("发布文章")']:
            try:
                pub_btn = await self._page.wait_for_selector(sel, timeout=3000, state="visible")
                if pub_btn:
                    await pub_btn.click()
                    print(f"[Playwright:toutiao] Clicked '预览并发布': {sel}")
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

        if not pub_btn:
            ss = await self._screenshot("toutiao_debug.png")
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"今日头条：未找到发布按钮。截图已保存: {ss}",
            )

        # Step 2: Handle cover selection panel.
        # Try to upload cover if provided; always fall back to 无封面 on any failure.
        await asyncio.sleep(1.5)  # let the panel fully render
        cover_uploaded = False
        if cover_path and Path(cover_path).exists():
            try:
                fi = await self._page.query_selector('input[type="file"]')
                if fi:
                    await fi.set_input_files(cover_path)
                    await asyncio.sleep(3)
                    cover_uploaded = True
                    print(f"[Playwright:toutiao] Uploaded cover: {cover_path}")
            except Exception as e:
                print(f"[Playwright:toutiao] Cover upload failed ({e}), falling back to 无封面")

        if not cover_uploaded:
            # ByteDance radio components ignore span.click(); use bounding-box mouse click.
            # scrollIntoView first so the element is within the 800px viewport.
            box = await self._page.evaluate("""() => {
                const inputs = Array.from(document.querySelectorAll('input[type="radio"]'));
                for (const inp of inputs) {
                    const c = inp.closest('label') || inp.parentElement;
                    if (c && c.textContent.includes('无封面')) {
                        inp.scrollIntoView({block: 'center'});
                        const r = inp.getBoundingClientRect();
                        if (r.width > 0) return {x: r.x + r.width/2, y: r.y + r.height/2, src: 'input'};
                    }
                }
                const all = Array.from(document.querySelectorAll('*'));
                for (const el of all) {
                    if (el.childElementCount === 0 && el.textContent.trim() === '无封面') {
                        const target = el.parentElement || el;
                        target.scrollIntoView({block: 'center'});
                        const r = target.getBoundingClientRect();
                        if (r.width > 0) return {x: r.x + r.width/2, y: r.y + r.height/2, src: 'text-parent'};
                    }
                }
                return null;
            }""")
            if box:
                await asyncio.sleep(0.3)  # let scroll settle
                await self._page.mouse.click(box['x'], box['y'])
                print(f"[Playwright:toutiao] Selected 无封面 at ({box['x']:.0f},{box['y']:.0f}) [{box['src']}]")
                await asyncio.sleep(0.8)
            else:
                print("[Playwright:toutiao] WARNING: could not locate 无封面")

        # Step 3: Scroll to bottom to ensure "预览并发布" button is visible, then click.
        await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
        for sel in ['button:has-text("预览并发布")', '.byte-btn-primary']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=5000, state="visible")
                if el:
                    await el.scroll_into_view_if_needed()
                    await el.click()
                    print(f"[Playwright:toutiao] Preview click: {sel}")
                    await asyncio.sleep(5)  # give the preview overlay time to appear
                    break
            except Exception:
                continue

        # Step 4: Click "确认发布" — this is the FINAL publish confirmation button
        # that appears in the mobile preview overlay.
        confirmed = False
        for sel in ['button:has-text("确认发布")', 'button:has-text("确认")']:
            try:
                el = await self._page.wait_for_selector(sel, timeout=8000, state="visible")
                if el:
                    await el.click()
                    confirmed = True
                    print(f"[Playwright:toutiao] Confirmed publish via: {sel}")
                    await asyncio.sleep(4)
                    break
            except Exception:
                continue

        if not confirmed:
            ss = await self._screenshot("toutiao_debug.png")
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"今日头条：未找到确认发布按钮。截图已保存: {ss}",
            )

        await self._save_cookies()
        current_url = self._page.url
        return PublishResult(status=PublishStatus.SUCCESS, platform_url=current_url or "https://mp.toutiao.com/")

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


def publish_sync(
    platform: str,
    title: str,
    body: str,
    summary: str = "",
    tags: list[str] | None = None,
    cover_path: str = "",
    image_paths: list[str] | None = None,
    account_name: str = "",
    author: str = "",
    location: str = "",
    topic_title: str = "",
    keywords: list[str] | None = None,
    headless: bool = True,
) -> PublishResult:
    """Synchronous wrapper for PlaywrightPublisher.publish()."""
    publisher = PlaywrightPublisher(platform, headless=headless)

    async def _run() -> PublishResult:
        try:
            return await publisher.publish(
                title=title,
                body=body,
                summary=summary,
                tags=tags,
                cover_path=cover_path,
                image_paths=image_paths,
                account_name=account_name,
                author=author,
                location=location,
                topic_title=topic_title,
                keywords=keywords,
            )
        finally:
            await publisher.close()

    return asyncio.run(_run())
