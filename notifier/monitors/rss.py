import logging
from datetime import datetime, timezone

import feedparser

from ..models import FeedItem
from .base import BaseMonitor

logger = logging.getLogger(__name__)


class RSSMonitor(BaseMonitor):
    async def fetch(self) -> list[FeedItem]:
        feeds = self.config.extra.get("feeds", [])
        items = []

        for feed_url in feeds:
            try:
                resp = await self.client.get(feed_url)
                resp.raise_for_status()
                parsed = feedparser.parse(resp.text)

                for entry in parsed.entries:
                    item_id = entry.get("id") or entry.get("link", "")
                    title = entry.get("title", "")
                    body = entry.get("summary", "") or entry.get("description", "")
                    url = entry.get("link", "")
                    author = entry.get("author", "")

                    published = entry.get("published_parsed")
                    ts = datetime(*published[:6], tzinfo=timezone.utc) if published else None

                    items.append(FeedItem(
                        source=self.name,
                        item_id=item_id,
                        title=title,
                        body=body,
                        url=url,
                        author=author,
                        timestamp=ts,
                    ))

            except Exception as e:
                logger.error(f"[{self.name}] Error fetching RSS feed {feed_url}: {e}")

        return items
