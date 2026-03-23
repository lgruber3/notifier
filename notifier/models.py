from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FeedItem:
    source: str
    item_id: str
    title: str
    body: str
    url: str
    author: str
    timestamp: datetime | None = None


@dataclass
class Notification:
    title: str
    body: str
    url: str
    priority: int = 3
    tags: list[str] = field(default_factory=list)
