from .config import KeywordRule
from .models import FeedItem


class Matcher:
    def __init__(self, global_keywords: list[KeywordRule], channel_keywords: list[KeywordRule] | None):
        # None → use global keywords; empty list → match everything
        if channel_keywords is None:
            self.rules = global_keywords
            self.match_all = False
        elif len(channel_keywords) == 0:
            self.rules = []
            self.match_all = True
        else:
            self.rules = channel_keywords
            self.match_all = False

    def matches(self, item: FeedItem) -> list[str]:
        if self.match_all:
            return ["*"]

        text = f"{item.title} {item.body}".lower()
        matched = []
        for rule in self.rules:
            if rule.compiled and rule.compiled.search(text):
                matched.append(rule.pattern)
        return matched
