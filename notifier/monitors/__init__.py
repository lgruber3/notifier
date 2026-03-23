from .rss import RSSMonitor
from .reddit import RedditMonitor

MONITOR_TYPES = {
    "rss": RSSMonitor,
    "reddit": RedditMonitor,
}


def create_monitor(channel_config, http_client):
    monitor_cls = MONITOR_TYPES.get(channel_config.type)
    if monitor_cls is None:
        raise ValueError(f"Unknown channel type: {channel_config.type}")
    return monitor_cls(channel_config, http_client)
