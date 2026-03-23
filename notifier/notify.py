import logging
import unicodedata

import httpx

from .models import Notification

logger = logging.getLogger(__name__)


def _sanitize_header(value: str) -> str:
    """Remove non-ASCII characters from header values to avoid illegal header errors."""
    # Replace smart quotes and common unicode with ASCII equivalents
    replacements = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
                    "\u2014": "-", "\u2013": "-", "\u2026": "..."}
    for char, repl in replacements.items():
        value = value.replace(char, repl)
    # Strip remaining non-ASCII
    return value.encode("ascii", errors="ignore").decode("ascii")


class NtfyNotifier:
    def __init__(self, server: str, topic: str, default_priority: int, client: httpx.AsyncClient, icon: str | None = None):
        self.url = f"{server.rstrip('/')}/{topic}"
        self.default_priority = default_priority
        self.client = client
        self.icon = icon

    async def send(self, notification: Notification):
        priority = notification.priority or self.default_priority
        headers = {
            "Title": _sanitize_header(notification.title[:250]),
            "Priority": str(priority),
            "Markdown": "yes",
        }
        if notification.url:
            headers["Click"] = notification.url
        if notification.tags:
            headers["Tags"] = ",".join(notification.tags[:5])
        if self.icon:
            headers["Icon"] = self.icon

        body = notification.body[:4000] if notification.body else ""

        try:
            resp = await self.client.post(self.url, content=body.encode("utf-8"), headers=headers)
            resp.raise_for_status()
            logger.info(f"Notification sent: {notification.title[:80]}")
        except httpx.HTTPError as e:
            logger.error(f"Failed to send notification: {e}")
