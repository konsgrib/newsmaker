"""Tests for SerpApiSourceCollector. No real network access is used."""

import json
import urllib.error
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

from newsmaker.sources import SerpApiSourceCollector


def _mock_urlopen(body: bytes):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _payload(*links: str) -> bytes:
    return json.dumps({"news_results": [{"link": link} for link in links]}).encode()


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("NEWSMAKER_SERPAPI_KEY", raising=False)

    with pytest.raises(ValueError):
        SerpApiSourceCollector()


def test_reads_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("NEWSMAKER_SERPAPI_KEY", "env-key")

    SerpApiSourceCollector()  # should not raise


def test_single_request_without_regions():
    with (
        patch(
            "newsmaker.sources.urllib.request.urlopen",
            return_value=_mock_urlopen(_payload("https://example.com/1")),
        ) as urlopen,
        patch("newsmaker.sources.trafilatura.fetch_url", return_value="<html/>"),
        patch("newsmaker.sources.trafilatura.extract", return_value="extracted text"),
    ):
        collector = SerpApiSourceCollector(api_key="test-key")
        documents = collector.collect("python", language="en")

    assert urlopen.call_count == 1
    requested_url = urlopen.call_args.args[0].full_url
    decoded = urllib.parse.unquote_plus(requested_url)
    assert "engine=google_news" in decoded
    assert "q=python" in decoded
    assert "hl=en" in decoded
    assert "api_key=test-key" in decoded
    assert "gl=" not in decoded
    assert [document.url for document in documents] == ["https://example.com/1"]


def test_queries_each_region_and_merges_deduplicated_results():
    responses = {
        "gl=lv": _payload("https://example.lv/1", "https://shared.example/x"),
        "gl=lt": _payload("https://example.lt/1", "https://shared.example/x"),
        "gl=ee": _payload("https://example.ee/1"),
    }

    def fake_urlopen(request, timeout, context):
        for marker, body in responses.items():
            if marker in request.full_url:
                return _mock_urlopen(body)
        raise AssertionError(f"unexpected request: {request.full_url}")

    with (
        patch("newsmaker.sources.urllib.request.urlopen", side_effect=fake_urlopen) as urlopen,
        patch("newsmaker.sources.trafilatura.fetch_url", return_value="<html/>"),
        patch("newsmaker.sources.trafilatura.extract", return_value="text"),
    ):
        collector = SerpApiSourceCollector(api_key="test-key", max_sources=10)
        documents = collector.collect("news", language="en", regions=["LV", "LT", "EE"])

    assert urlopen.call_count == 3
    urls = [document.url for document in documents]
    assert urls == [
        "https://example.lv/1",
        "https://shared.example/x",
        "https://example.lt/1",
        "https://example.ee/1",
    ]


def test_stops_once_max_sources_reached_even_with_more_regions():
    def fake_urlopen(request, timeout, context):
        return _mock_urlopen(_payload("https://example.com/a", "https://example.com/b"))

    with (
        patch("newsmaker.sources.urllib.request.urlopen", side_effect=fake_urlopen),
        patch("newsmaker.sources.trafilatura.fetch_url", return_value="<html/>"),
        patch("newsmaker.sources.trafilatura.extract", return_value="text"),
    ):
        collector = SerpApiSourceCollector(api_key="test-key", max_sources=1)
        documents = collector.collect("news", language="en", regions=["LV", "LT", "EE"])

    assert len(documents) == 1


def test_skips_urls_that_fail_extraction():
    with (
        patch(
            "newsmaker.sources.urllib.request.urlopen",
            return_value=_mock_urlopen(_payload("https://example.com/1", "https://example.com/2")),
        ),
        patch("newsmaker.sources.trafilatura.fetch_url", side_effect=["<html/>", None]),
        patch("newsmaker.sources.trafilatura.extract", return_value="text"),
    ):
        collector = SerpApiSourceCollector(api_key="test-key")
        documents = collector.collect("news", language="en")

    assert [document.url for document in documents] == ["https://example.com/1"]


def test_mapped_region_adds_a_site_or_filter():
    with patch(
        "newsmaker.sources.urllib.request.urlopen",
        return_value=_mock_urlopen(_payload()),
    ) as urlopen:
        collector = SerpApiSourceCollector(api_key="test-key")
        collector.collect("news", language="ru", regions=["LV"])

    requested_url = urlopen.call_args.args[0].full_url
    decoded = urllib.parse.unquote_plus(requested_url)
    assert "(site:delfi.lv OR site:rus.lsm.lv OR site:rus.tvnet.lv OR site:press.lv)" in decoded
    assert "gl=lv" in decoded


def test_unmapped_region_gets_no_site_filter():
    with patch(
        "newsmaker.sources.urllib.request.urlopen",
        return_value=_mock_urlopen(_payload()),
    ) as urlopen:
        collector = SerpApiSourceCollector(api_key="test-key")
        collector.collect("news", language="en", regions=["ZZ"])

    requested_url = urlopen.call_args.args[0].full_url
    decoded = urllib.parse.unquote_plus(requested_url)
    assert "site:" not in decoded
    assert "gl=zz" in decoded


def test_returns_empty_list_when_search_fails():
    with patch(
        "newsmaker.sources.urllib.request.urlopen",
        side_effect=urllib.error.URLError("boom"),
    ):
        collector = SerpApiSourceCollector(api_key="test-key")
        documents = collector.collect("news", language="en")

    assert documents == []
