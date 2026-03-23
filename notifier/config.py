import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class NtfyConfig:
    server: str = "https://ntfy.sh"
    topic: str = "changeme"
    default_priority: int = 3


@dataclass
class KeywordRule:
    pattern: str
    is_regex: bool = False
    compiled: re.Pattern | None = None

    def __post_init__(self):
        if self.is_regex:
            self.compiled = re.compile(self.pattern, re.IGNORECASE)
        else:
            self.compiled = re.compile(re.escape(self.pattern), re.IGNORECASE)


@dataclass
class ChannelConfig:
    name: str
    type: str
    poll_interval: int = 600
    priority: int | None = None
    keywords: list[KeywordRule] | None = None  # None = inherit global, [] = match all
    # Type-specific fields stored as dict
    extra: dict = field(default_factory=dict)


@dataclass
class WebConfig:
    enabled: bool = True
    port: int = 8550


@dataclass
class AppConfig:
    ntfy: NtfyConfig
    global_keywords: list[KeywordRule]
    channels: list[ChannelConfig]
    log_level: str = "INFO"
    notify_on_first_run: bool = False
    web: WebConfig = None

    def __post_init__(self):
        if self.web is None:
            self.web = WebConfig()


def _parse_keywords(raw: list | None) -> list[KeywordRule] | None:
    if raw is None:
        return None
    rules = []
    for item in raw:
        if isinstance(item, str):
            rules.append(KeywordRule(pattern=item))
        elif isinstance(item, dict):
            rules.append(KeywordRule(
                pattern=item["pattern"],
                is_regex=item.get("regex", False),
            ))
    return rules


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    ntfy_raw = raw.get("ntfy", {})
    ntfy = NtfyConfig(
        server=ntfy_raw.get("server", "https://ntfy.sh"),
        topic=ntfy_raw.get("topic", "changeme"),
        default_priority=ntfy_raw.get("default_priority", 3),
    )

    global_keywords = _parse_keywords(raw.get("keywords", [])) or []

    channels = []
    for ch in raw.get("channels", []):
        name = ch.pop("name")
        ch_type = ch.pop("type")
        poll_interval = ch.pop("poll_interval", 600)
        priority = ch.pop("priority", None)
        has_keywords_key = "keywords" in ch
        kw_raw = ch.pop("keywords", None)

        # keywords key present but empty list → match all; key absent → None (inherit)
        if not has_keywords_key:
            keywords = None
        else:
            keywords = _parse_keywords(kw_raw) if kw_raw else []

        channels.append(ChannelConfig(
            name=name,
            type=ch_type,
            poll_interval=poll_interval,
            priority=priority,
            keywords=keywords,
            extra=ch,  # remaining fields (accounts, feeds, subreddits, etc.)
        ))

    logging_raw = raw.get("logging", {})
    web_raw = raw.get("web", {})
    web = WebConfig(
        enabled=web_raw.get("enabled", True),
        port=web_raw.get("port", 8550),
    )

    return AppConfig(
        ntfy=ntfy,
        global_keywords=global_keywords,
        channels=channels,
        log_level=logging_raw.get("level", "INFO"),
        notify_on_first_run=raw.get("notify_on_first_run", False),
        web=web,
    )


def _keywords_to_raw(keywords: list[KeywordRule] | None) -> list | None:
    if keywords is None:
        return None
    result = []
    for kw in keywords:
        if kw.is_regex:
            result.append({"pattern": kw.pattern, "regex": True})
        else:
            result.append(kw.pattern)
    return result


def save_config(config: AppConfig, path: str | Path):
    """Serialize AppConfig back to YAML."""
    raw = {
        "ntfy": {
            "server": config.ntfy.server,
            "topic": config.ntfy.topic,
            "default_priority": config.ntfy.default_priority,
        },
        "notify_on_first_run": config.notify_on_first_run,
        "keywords": _keywords_to_raw(config.global_keywords) or [],
        "logging": {"level": config.log_level},
        "web": {
            "enabled": config.web.enabled,
            "port": config.web.port,
        },
        "channels": [],
    }

    for ch in config.channels:
        ch_raw = {
            "name": ch.name,
            "type": ch.type,
            "poll_interval": ch.poll_interval,
        }
        if ch.priority is not None:
            ch_raw["priority"] = ch.priority
        if ch.keywords is not None:
            ch_raw["keywords"] = _keywords_to_raw(ch.keywords)
        # Merge extra fields (subreddits, feeds, sort, etc.)
        ch_raw.update(ch.extra)
        raw["channels"].append(ch_raw)

    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
