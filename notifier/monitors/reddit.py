import logging
import re
from datetime import datetime, timezone

import feedparser

from ..models import FeedItem
from .base import BaseMonitor

logger = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return TAG_RE.sub("", text).strip()


class RedditMonitor(BaseMonitor):
    """Monitor Reddit via old.reddit.com RSS (most reliable from servers)."""

    async def fetch(self) -> list[FeedItem]:
        subreddits = self.config.extra.get("subreddits", [])
        sort = self.config.extra.get("sort", "new")
        items = []

        for sub in subreddits:
            result = await self._fetch_old_reddit(sub, sort)
            if result is None:
                result = await self._fetch_json(sub, sort)
            if result is not None:
                items.extend(result)

        return items

    async def _fetch_old_reddit(self, sub: str, sort: str) -> list[FeedItem] | None:
        """Fetch via old.reddit.com RSS — least likely to be blocked."""
        url = f"https://old.reddit.com/r/{sub}/{sort}.rss"
        try:
            resp = await self.client.get(url, headers={
                "User-Agent": BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            resp.raise_for_status()
            parsed = feedparser.parse(resp.text)
            if not parsed.entries:
                logger.warning(f"[{self.name}] old.reddit RSS returned no entries for r/{sub}")
                return None

            items = []
            for entry in parsed.entries:
                item_id = entry.get("id") or entry.get("link", "")
                title = entry.get("title", "")
                body = strip_html(entry.get("summary", "") or entry.get("description", ""))

                published = entry.get("published_parsed")
                ts = datetime(*published[:6], tzinfo=timezone.utc) if published else None

                items.append(FeedItem(
                    source=self.name,
                    item_id=item_id,
                    title=title,
                    body=body,
                    url=entry.get("link", ""),
                    author=entry.get("author", "").lstrip("/u/"),
                    timestamp=ts,
                ))
            return items
        except Exception as e:
            logger.warning(f"[{self.name}] old.reddit RSS failed for r/{sub}: {e}")
            return None

    async def _fetch_json(self, sub: str, sort: str) -> list[FeedItem] | None:
        """Fallback: JSON API via www.reddit.com."""
        url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit=25"
        try:
            resp = await self.client.get(url, headers={
                "User-Agent": BROWSER_UA,
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
            logger.error(f"[{self.name}] JSON API also failed for r/{sub}: {e}")
            return None
