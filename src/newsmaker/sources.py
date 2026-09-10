"""Source-article discovery (GDELT or SerpApi) and text extraction (trafilatura)."""

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

import certifi
import trafilatura

logger = logging.getLogger(__name__)

_USER_AGENT = "newsmaker/0.1 (+https://pypi.org/project/newsmaker/)"

# Extraction (one HTTP fetch + parse per candidate URL) is I/O-bound, so a
# small thread pool lets candidates be fetched concurrently instead of one
# at a time; bounded so a large candidate pool doesn't open too many
# connections at once.
_MAX_EXTRACTION_WORKERS = 5


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


_FETCH_MAX_ATTEMPTS = 3
_FETCH_RETRY_DELAY_SECONDS = 2.0


def _extract_text(url: str) -> str | None:
    downloaded = None
    for attempt in range(1, _FETCH_MAX_ATTEMPTS + 1):
        try:
            downloaded = trafilatura.fetch_url(url)
        except Exception as exc:  # noqa: BLE001 - one bad source must not abort the run
            logger.debug(
                "fetch attempt %d/%d failed for %s: %s", attempt, _FETCH_MAX_ATTEMPTS, url, exc
            )
            downloaded = None
        if downloaded:
            break
        if attempt < _FETCH_MAX_ATTEMPTS:
            time.sleep(_FETCH_RETRY_DELAY_SECONDS)

    if not downloaded:
        logger.debug("could not fetch %s after %d attempt(s)", url, _FETCH_MAX_ATTEMPTS)
        return None
    text = trafilatura.extract(downloaded, favor_recall=True, include_comments=False)
    if not text:
        logger.debug("trafilatura extracted no text from %s", url)
    return text


def _extract_documents(candidate_urls: list[str], max_documents: int) -> list[SourceDocument]:
    """Extract text from `candidate_urls` concurrently, stopping once `max_documents`
    have succeeded. Results preserve the original candidate order."""
    if not candidate_urls:
        return []

    documents: list[SourceDocument] = []
    executor = ThreadPoolExecutor(max_workers=min(_MAX_EXTRACTION_WORKERS, len(candidate_urls)))
    try:
        results = zip(candidate_urls, executor.map(_extract_text, candidate_urls), strict=True)
        for url, text in results:
            if text:
                documents.append(SourceDocument(url=url, text=text))
                if len(documents) >= max_documents:
                    break
    finally:
        # Cancel any candidates not yet started; don't block on ones still
        # running -- we already have what we need.
        executor.shutdown(wait=False, cancel_futures=True)

    logger.debug(
        "extracted %d/%d document(s) from %d candidate(s)",
        len(documents),
        max_documents,
        len(candidate_urls),
    )
    return documents


_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT asks unauthenticated callers to stay under one request every 5
# seconds; a single retry after that wait covers the common case where a
# burst of other traffic (or a previous call from this process) tripped it.
_RATE_LIMIT_WAIT_SECONDS = 5.0

_DEFAULT_SOURCE_LANGUAGE_NAMES = {
    "ru": "russian",
    "en": "english",
}

# GDELT's `sourcecountry:` filter takes the country's full name (no
# spaces), not the ISO 3166-1 alpha-2 code that `regions` uses elsewhere
# (that ISO code matches Google Trends' `geo` param, not GDELT's FIPS-ish
# country codes) -- hence this small translation table.
_DEFAULT_SOURCE_COUNTRY_NAMES = {
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

    `language_names`/`country_names` extend/override the built-in
    language/country name tables GDELT's `sourcelang:`/`sourcecountry:`
    filters expect (merged per key, not a full replacement) -- e.g. to
    add a language or country not already covered.
    """

    def __init__(
        self,
        *,
        max_sources: int = 5,
        candidate_pool: int = 15,
        timeout: float = 10.0,
        language_names: dict[str, str] | None = None,
        country_names: dict[str, str] | None = None,
    ) -> None:
        self._max_sources = max_sources
        self._candidate_pool = candidate_pool
        self._timeout = timeout
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        # `language_names`/`country_names` extend/override the built-in
        # maps per key, rather than replacing them outright -- same
        # merge behavior as `SerpApiSourceCollector(region_domains=...)`.
        self._language_names = {**_DEFAULT_SOURCE_LANGUAGE_NAMES, **(language_names or {})}
        self._country_names = {**_DEFAULT_SOURCE_COUNTRY_NAMES, **(country_names or {})}

    def collect(
        self, query: str, *, language: str, regions: list[str] | None = None
    ) -> list[SourceDocument]:
        """Return up to `max_sources` extracted source documents about `query`."""
        candidate_urls = self._search(query, language=language, regions=regions)
        return _extract_documents(candidate_urls, self._max_sources)

    def _search(self, query: str, *, language: str, regions: list[str] | None) -> list[str]:
        full_query = query

        source_lang = self._language_names.get(language)
        if source_lang:
            full_query += f" sourcelang:{source_lang}"

        if regions:
            country_names = [self._country_names.get(region, region.lower()) for region in regions]
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
            logger.warning("GDELT search failed for %r", query)
            return []
        urls = [article["url"] for article in payload.get("articles", []) if article.get("url")]
        logger.debug("GDELT returned %d candidate(s) for %r", len(urls), query)
        return urls

    def _fetch_json(self, url: str, *, retry_on_rate_limit: bool) -> dict[str, Any] | None:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=self._ssl_context
            ) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and retry_on_rate_limit:
                logger.warning(
                    "GDELT rate-limited us (429), retrying once after %.0fs",
                    _RATE_LIMIT_WAIT_SECONDS,
                )
                time.sleep(_RATE_LIMIT_WAIT_SECONDS)
                return self._fetch_json(url, retry_on_rate_limit=False)
            logger.warning("GDELT request failed: HTTP %s", exc.code)
            return None
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            logger.warning("GDELT request failed: %s", exc)
            return None


_SERPAPI_URL = "https://serpapi.com/search"

# `gl`/`hl` alone only target the Google News *audience* (what a reader in
# that region would see) -- they do not restrict results to outlets
# actually based there (confirmed live: regions=["LV","LT","EE"] with only
# `gl` returned mainstream Russian national outlets, not Baltic ones). To
# actually restrict to Baltic-*published* sources, this list of major
# regional outlets is combined into a `site:` OR-filter, the same way
# GDELT's `sourcecountry:` does it natively. Not exhaustive -- extend it
# via `SerpApiSourceCollector(region_domains=...)`; a region missing from
# the (merged) map gets no site restriction (falls back to `gl`/`hl`
# audience-targeting only).
_DEFAULT_REGION_DOMAINS = {
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
        region_domains: dict[str, list[str]] | None = None,
    ) -> None:
        api_key = api_key or os.environ.get("NEWSMAKER_SERPAPI_KEY")
        if not api_key:
            raise ValueError("api_key is required (directly or via NEWSMAKER_SERPAPI_KEY)")
        self._api_key = api_key
        self._max_sources = max_sources
        self._candidate_pool_per_region = candidate_pool_per_region
        self._timeout = timeout
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        # `region_domains` extends/overrides the built-in map per region
        # key, rather than replacing it outright.
        self._region_domains = {**_DEFAULT_REGION_DOMAINS, **(region_domains or {})}

    def collect(
        self, query: str, *, language: str, regions: list[str] | None = None
    ) -> list[SourceDocument]:
        """Return up to `max_sources` extracted source documents about `query`."""
        candidate_urls = self._search(query, language=language, regions=regions)
        return _extract_documents(candidate_urls, self._max_sources)

    def _search(self, query: str, *, language: str, regions: list[str] | None) -> list[str]:
        geos: list[str | None] = list(regions) if regions else [None]
        urls: list[str] = []
        seen: set[str] = set()
        for geo in geos:
            for url in self._search_one_region(query, language=language, geo=geo):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        logger.debug("SerpApi returned %d candidate(s) for %r", len(urls), query)
        return urls

    def _search_one_region(self, query: str, *, language: str, geo: str | None) -> list[str]:
        full_query = query
        domains = self._region_domains.get(geo.upper()) if geo else None
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
            logger.warning("SerpApi search failed for %r (geo=%s)", query, geo)
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
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            logger.warning("SerpApi request failed: %s", exc)
            return None
