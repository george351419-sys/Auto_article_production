"""Stub publisher — safe default that logs instead of posting.

Does NOT actually publish to any platform. Use StubPublisher for testing
and development. For real publishing, enable PlaywrightPublisher.
"""

from __future__ import annotations

from datetime import UTC, datetime

from autopublish.base import PublishResult, PublishStatus


class StubPublisher:
    """Stub publisher that logs publish requests instead of posting.

    Safe default for development. Replace with PlaywrightPublisher when ready.
    """

    def __init__(self, platform: str):
        self.platform = platform
        self.log: list[dict] = []

    def publish(
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
        entry = {
            "platform": self.platform,
            "title": title,
            "body_length": len(body),
            "summary": summary[:50] if summary else "",
            "tags": tags or [],
            "keywords": keywords or [],
            "cover_path": cover_path,
            "image_count": len(image_paths or []),
            "account_name": account_name,
            "author": author,
            "location": location,
            "topic_title": topic_title,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.log.append(entry)

        print(f"[StubPublisher:{self.platform}] Would publish: {title}")
        print(f"  account={account_name}, author={author}, location={location}")
        print(f"  tags={tags}, keywords={keywords}, topic={topic_title}, images={len(image_paths or [])}")
        if body:
            print(f"  body preview: {body[:100]}...")

        return PublishResult(
            status=PublishStatus.SUCCESS,
            platform_url=f"https://{self.platform}.example.com/post/stub-{hash(title) % 100000:05d}",
        )
