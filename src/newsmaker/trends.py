"""Trending-topic detection via Google Trends' public "Daily Search Trends" RSS feed.

This is the same unauthenticated feed that powers Google Trends' own
"Trending Now" page (``https://trends.google.com/trending/rss?geo=<geo>``).
It only lists the current overall trending searches for a region -- it is
not scoped to an arbitrary keyword -- so ``GoogleTrendsRssProvider`` looks
for a trend whose title or related news headlines mention the requested
topic, and reports when nothing matches so the caller can decide how to
fall back.
"""

import ssl
import urllib.error
import urllib.request
from typing import Protocol
from xml.etree import ElementTree

import certifi

_RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"
_RSS_NAMESPACE = {"ht": "https://trends.google.com/trending/rss"}
_USER_AGENT = "newsmaker/0.1 (+https://pypi.org/project/newsmaker/)"

# Google Trends' RSS feed is scoped by region, not language, so pick a
# region likely to publish trends in the requested output language when
# the caller doesn't pass explicit `regions`.
_GEO_BY_LANGUAGE = {
    "ru": "RU",
    "en": "US",
}
_DEFAULT_GEO = "US"

# Words too short to be a meaningful match signal (avoids matching on
# short common words that happen to be substrings of unrelated trends).
_MIN_MATCH_WORD_LENGTH = 3


class TrendsProvider(Protocol):
    """A source of the currently hottest news angle for a topic."""

    def get_trending_topic(
        self, topic: str, *, language: str, regions: list[str] | None = None
    ) -> str | None:
        """Return the currently trending angle related to `topic`, or None if none is found."""
        ...


class GoogleTrendsRssProvider:
    """Matches `topic` against Google Trends' public RSS feed of current trends."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    def get_trending_topic(
        self, topic: str, *, language: str, regions: list[str] | None = None
    ) -> str | None:
        topic_words = [
            word.lower() for word in topic.split() if len(word) >= _MIN_MATCH_WORD_LENGTH
        ]
        if not topic_words:
            return None

        geos = regions if regions else [_GEO_BY_LANGUAGE.get(language, _DEFAULT_GEO)]
        for geo in geos:
            root = self._fetch_feed(geo)
            if root is None:
                continue
            match = self._find_match(root, topic_words)
            if match is not None:
                return match

        return None

    @staticmethod
    def _find_match(root: ElementTree.Element, topic_words: list[str]) -> str | None:
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            headlines = [
                headline.strip()
                for news_item in item.findall("ht:news_item", _RSS_NAMESPACE)
                if (headline := news_item.findtext("ht:news_item_title", namespaces=_RSS_NAMESPACE))
            ]
            haystack = " ".join([title, *headlines]).lower()
            if any(word in haystack for word in topic_words):
                best_headline = next((headline for headline in headlines if headline), title)
                return f"{title}: {best_headline}" if best_headline != title else title
        return None

    def _fetch_feed(self, geo: str) -> ElementTree.Element | None:
        request = urllib.request.Request(
            _RSS_URL.format(geo=geo), headers={"User-Agent": _USER_AGENT}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=self._ssl_context
            ) as response:
                data = response.read()
        except urllib.error.URLError:
            return None
        try:
            return ElementTree.fromstring(data)
        except ElementTree.ParseError:
            return None


class NullTrendsProvider:
    """A `TrendsProvider` that never looks anything up.

    Use this to skip the Google Trends step entirely -- e.g. for evergreen
    topics that rarely show up as an actual Google Trends "trending
    search", where every real call would just fall back to the raw topic
    anyway. `Client` doesn't need to know the difference: this still
    satisfies `TrendsProvider`, so the rest of the pipeline is unaffected.
    """

    def get_trending_topic(
        self, topic: str, *, language: str, regions: list[str] | None = None
    ) -> str | None:
        return None
