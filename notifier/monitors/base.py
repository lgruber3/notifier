import logging
from abc import ABC, abstractmethod

import httpx

from ..config import ChannelConfig
from ..models import FeedItem

logger = logging.getLogger(__name__)


class BaseMonitor(ABC):
    def __init__(self, config: ChannelConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client
        self.name = config.name

    @abstractmethod
    async def fetch(self) -> list[FeedItem]:
        ...
