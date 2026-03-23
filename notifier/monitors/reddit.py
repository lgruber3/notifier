import logging
from datetime import datetime, timezone

import feedparser

from ..models import FeedItem
from .base import BaseMonitor

logger = logging.getLogger(__name__)


class RedditMonitor(BaseMonitor):
    """Monitor Reddit via JSON API with RSS fallback."""

    async def _fetch_json(self, sub: str, sort: str) -> list[FeedItem] | None:
        url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit=25"
        try:
            resp = await self.client.get(url, headers={
                "User-Agent": "notifier/1.0 (personal keyword monitor)",
            })
            resp.raise_for_status()
            data = resp.json()

            items = []
            for post in data.get("data", {}).get("children", []):
                d = post["data"]
                items.append(FeedItem(
                    source=self.name,
                    item_id=d["id"],
                    title=d.get("title", ""),
                    body=d.get("selftext", ""),
                    url=f"https://www.reddit.com{d.get('permalink', '')}",
                    author=d.get("author", ""),
                    timestamp=datetime.fromtimestamp(d["created_utc"], tz=timezone.utc) if d.get("created_utc") else None,
                ))
            return items
        except Exception as e:
            logger.warning(f"[{self.name}] JSON API failed for r/{sub}: {e}")
            return None

    async def _fetch_rss(self, sub: str) -> list[FeedItem]:
        url = f"https://www.reddit.com/r/{sub}.rss"
        try:
            resp = await self.client.get(url, headers={
                "User-Agent": "notifier/1.0 (personal keyword monitor)",
            })
            resp.raise_for_status()
            parsed = feedparser.parse(resp.text)

            items = []
            for entry in parsed.entries:
                item_id = entry.get("id") or entry.get("link", "")
                items.append(FeedItem(
                    source=self.name,
                    item_id=item_id,
                    title=entry.get("title", ""),
                    body=entry.get("summary", "") or entry.get("description", ""),
                    url=entry.get("link", ""),
                    author=entry.get("author", ""),
                    timestamp=datetime(*entry.published_parsed[:6], tzinfo=timezone.utc) if entry.get("published_parsed") else None,
                ))
            return items
        except Exception as e:
            logger.error(f"[{self.name}] RSS also failed for r/{sub}: {e}")
            return []

    async def fetch(self) -> list[FeedItem]:
        subreddits = self.config.extra.get("subreddits", [])
        sort = self.config.extra.get("sort", "new")
        items = []

        for sub in subreddits:
            result = await self._fetch_json(sub, sort)
            if result is not None:
                items.extend(result)
            else:
                items.extend(await self._fetch_rss(sub))

        return items
