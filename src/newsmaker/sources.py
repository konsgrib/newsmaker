"""Source-article discovery (GDELT or SerpApi) and text extraction (trafilatura)."""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

import certifi
import trafilatura

_USER_AGENT = "newsmaker/0.1 (+https://pypi.org/project/newsmaker/)"


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Full text extracted from one source article."""

    url: str
    text: str


class SourceProvider(Protocol):
    """A source of extracted source-article text about a topic."""

    def collect(
        self, query: str, *, language: str, regions: list[str] | None = None
    ) -> list[SourceDocument]:
        """Return up to a provider-chosen number of source documents about `query`."""
        ...


def _extract_text(url: str) -> str | None:
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None
    return trafilatura.extract(downloaded, favor_recall=True, include_comments=False)


_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT asks unauthenticated callers to stay under one request every 5
# seconds; a single retry after that wait covers the common case where a
# burst of other traffic (or a previous call from this process) tripped it.
_RATE_LIMIT_WAIT_SECONDS = 5.0

_SOURCE_LANGUAGE_NAMES = {
    "ru": "russian",
    "en": "english",
}

# GDELT's `sourcecountry:` filter takes the country's full name (no
# spaces), not the ISO 3166-1 alpha-2 code that `regions` uses elsewhere
# (that ISO code matches Google Trends' `geo` param, not GDELT's FIPS-ish
# country codes) -- hence this small translation table.
_SOURCE_COUNTRY_NAMES = {
    "LV": "latvia",
    "LT": "lithuania",
    "EE": "estonia",
    "RU": "russia",
    "US": "unitedstates",
    "GB": "unitedkingdom",
}


class SourceCollector:
    """Finds source articles about a topic via GDELT (free, unauthenticated) and
    extracts their text.

    GDELT enforces an aggressive, undocumented rate limit on unauthenticated
    callers -- under sustained use it can return HTTP 429 for extended
    periods, even from an IP that has never called it before. When that
    makes this provider unusable, pass a `SerpApiSourceCollector` instead;
    both implement the same `SourceProvider` interface.
    """

    def __init__(
        self,
        *,
        max_sources: int = 5,
        candidate_pool: int = 15,
        timeout: float = 10.0,
    ) -> None:
        self._max_sources = max_sources
        self._candidate_pool = candidate_pool
        self._timeout = timeout
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    def collect(
        self, query: str, *, language: str, regions: list[str] | None = None
    ) -> list[SourceDocument]:
        """Return up to `max_sources` extracted source documents about `query`."""
        documents: list[SourceDocument] = []
        for url in self._search(query, language=language, regions=regions):
            if len(documents) >= self._max_sources:
                break
            text = _extract_text(url)
            if text:
                documents.append(SourceDocument(url=url, text=text))
        return documents

    def _search(self, query: str, *, language: str, regions: list[str] | None) -> list[str]:
        full_query = query

        source_lang = _SOURCE_LANGUAGE_NAMES.get(language)
        if source_lang:
            full_query += f" sourcelang:{source_lang}"

        if regions:
            country_names = [
                _SOURCE_COUNTRY_NAMES.get(region, region.lower()) for region in regions
            ]
            country_filter = " OR ".join(f"sourcecountry:{name}" for name in country_names)
            full_query += f" ({country_filter})"

        params = {
            "query": full_query,
            "mode": "artlist",
            "maxrecords": str(self._candidate_pool),
            "format": "json",
        }
        url = f"{_GDELT_URL}?{urllib.parse.urlencode(params)}"
        payload = self._fetch_json(url, retry_on_rate_limit=True)
        if payload is None:
            return []
        return [article["url"] for article in payload.get("articles", []) if article.get("url")]

    def _fetch_json(self, url: str, *, retry_on_rate_limit: bool) -> dict[str, Any] | None:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=self._ssl_context
            ) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and retry_on_rate_limit:
                time.sleep(_RATE_LIMIT_WAIT_SECONDS)
                return self._fetch_json(url, retry_on_rate_limit=False)
            return None
        # Python 3.14 made the parentheses around a multi-type except
        # optional; ruff's formatter removes them for this target version.
        except urllib.error.URLError, json.JSONDecodeError:
            return None


_SERPAPI_URL = "https://serpapi.com/search"

# `gl`/`hl` alone only target the Google News *audience* (what a reader in
# that region would see) -- they do not restrict results to outlets
# actually based there (confirmed live: regions=["LV","LT","EE"] with only
# `gl` returned mainstream Russian national outlets, not Baltic ones). To
# actually restrict to Baltic-*published* sources, this list of major
# regional outlets is combined into a `site:` OR-filter, the same way
# GDELT's `sourcecountry:` does it natively. Not exhaustive -- extend as
# needed; a region missing from this map gets no site restriction (falls
# back to `gl`/`hl` audience-targeting only).
_REGION_DOMAINS = {
    "LV": ["delfi.lv", "rus.lsm.lv", "rus.tvnet.lv", "press.lv"],
    "LT": ["delfi.lt", "lrt.lt"],
    "EE": ["delfi.ee", "rus.err.ee", "rus.postimees.ee"],
}


class SerpApiSourceCollector:
    """Finds source articles about a topic via SerpApi's Google News engine.

    A paid alternative to the free `SourceCollector` (GDELT), for when
    GDELT's rate limiting makes it unusable. Requires a SerpApi account and
    API key (https://serpapi.com/) -- pass it directly or set
    `NEWSMAKER_SERPAPI_KEY`.

    SerpApi's `gl` (country) and `hl` (language) parameters each take a
    single value, unlike GDELT's `sourcecountry:`/`sourcelang:`, which can
    be OR'd together in one query. So when `regions` has more than one
    entry, this issues one request per region and merges the results,
    instead of GDELT's single combined-filter query.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        max_sources: int = 5,
        candidate_pool_per_region: int = 10,
        timeout: float = 10.0,
    ) -> None:
        api_key = api_key or os.environ.get("NEWSMAKER_SERPAPI_KEY")
        if not api_key:
            raise ValueError("api_key is required (directly or via NEWSMAKER_SERPAPI_KEY)")
        self._api_key = api_key
        self._max_sources = max_sources
        self._candidate_pool_per_region = candidate_pool_per_region
        self._timeout = timeout
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    def collect(
        self, query: str, *, language: str, regions: list[str] | None = None
    ) -> list[SourceDocument]:
        """Return up to `max_sources` extracted source documents about `query`."""
        documents: list[SourceDocument] = []
        for url in self._search(query, language=language, regions=regions):
            if len(documents) >= self._max_sources:
                break
            text = _extract_text(url)
            if text:
                documents.append(SourceDocument(url=url, text=text))
        return documents

    def _search(self, query: str, *, language: str, regions: list[str] | None) -> list[str]:
        geos: list[str | None] = list(regions) if regions else [None]
        urls: list[str] = []
        seen: set[str] = set()
        for geo in geos:
            for url in self._search_one_region(query, language=language, geo=geo):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        return urls

    def _search_one_region(self, query: str, *, language: str, geo: str | None) -> list[str]:
        full_query = query
        domains = _REGION_DOMAINS.get(geo.upper()) if geo else None
        if domains:
            site_filter = " OR ".join(f"site:{domain}" for domain in domains)
            full_query += f" ({site_filter})"

        params = {
            "engine": "google_news",
            "q": full_query,
            "hl": language,
            "api_key": self._api_key,
        }
        if geo:
            params["gl"] = geo.lower()
        url = f"{_SERPAPI_URL}?{urllib.parse.urlencode(params)}"
        payload = self._fetch_json(url)
        if payload is None:
            return []
        links = [
            article["link"] for article in payload.get("news_results", []) if article.get("link")
        ]
        return links[: self._candidate_pool_per_region]

    def _fetch_json(self, url: str) -> dict[str, Any] | None:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=self._ssl_context
            ) as response:
                return json.loads(response.read())
        except urllib.error.URLError, json.JSONDecodeError:
            return None
