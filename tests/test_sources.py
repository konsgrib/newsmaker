"""Tests for SourceCollector. No real network access is used."""

import json
import urllib.error
import urllib.parse
from unittest.mock import MagicMock, patch

from newsmaker.sources import SourceCollector

_GDELT_PAYLOAD = json.dumps(
    {
        "articles": [
            {"url": "https://example.com/1"},
            {"url": "https://example.com/2"},
            {"url": "https://example.com/3"},
        ]
    }
).encode()


def _mock_urlopen(body: bytes):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_collects_extracted_documents_up_to_max_sources():
    collector = SourceCollector(max_sources=2)
    with (
        patch(
            "newsmaker.sources.urllib.request.urlopen", return_value=_mock_urlopen(_GDELT_PAYLOAD)
        ),
        patch("newsmaker.sources.trafilatura.fetch_url", return_value="<html>...</html>"),
        patch("newsmaker.sources.trafilatura.extract", return_value="extracted text"),
    ):
        documents = collector.collect("python", language="en")

    assert [document.url for document in documents] == [
        "https://example.com/1",
        "https://example.com/2",
    ]
    assert all(document.text == "extracted text" for document in documents)


def test_skips_urls_that_fail_extraction():
    # Extraction now runs concurrently, so `fetch_url`'s behavior must be
    # keyed by the URL argument, not by call order (a positional
    # `side_effect` list isn't safe to consume from multiple threads).
    fetchable = {"https://example.com/1", "https://example.com/3"}

    collector = SourceCollector(max_sources=5)
    with (
        patch(
            "newsmaker.sources.urllib.request.urlopen", return_value=_mock_urlopen(_GDELT_PAYLOAD)
        ),
        patch(
            "newsmaker.sources.trafilatura.fetch_url",
            side_effect=lambda url: "<html/>" if url in fetchable else None,
        ),
        patch("newsmaker.sources.trafilatura.extract", return_value="extracted text"),
    ):
        documents = collector.collect("python", language="en")

    assert {document.url for document in documents} == fetchable


def test_retries_once_on_rate_limit_then_succeeds():
    rate_limited = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
    with (
        patch(
            "newsmaker.sources.urllib.request.urlopen",
            side_effect=[rate_limited, _mock_urlopen(_GDELT_PAYLOAD)],
        ),
        patch("newsmaker.sources.time.sleep") as mock_sleep,
        patch("newsmaker.sources.trafilatura.fetch_url", return_value="<html/>"),
        patch("newsmaker.sources.trafilatura.extract", return_value="extracted text"),
    ):
        collector = SourceCollector(max_sources=5)
        documents = collector.collect("python", language="en")

    mock_sleep.assert_called_once()
    assert len(documents) == 3


def test_returns_empty_list_when_search_fails():
    with patch(
        "newsmaker.sources.urllib.request.urlopen",
        side_effect=urllib.error.URLError("boom"),
    ):
        collector = SourceCollector()
        documents = collector.collect("python", language="en")

    assert documents == []


def test_regions_add_a_sourcecountry_or_filter_to_the_query():
    with patch(
        "newsmaker.sources.urllib.request.urlopen", return_value=_mock_urlopen(_GDELT_PAYLOAD)
    ) as urlopen:
        collector = SourceCollector()
        collector.collect("news", language="en", regions=["LV", "LT", "EE"])

    requested_url = urlopen.call_args.args[0].full_url
    decoded = urllib.parse.unquote_plus(requested_url)
    assert "(sourcecountry:latvia OR sourcecountry:lithuania OR sourcecountry:estonia)" in decoded


def test_unmapped_region_code_falls_back_to_lowercased_code():
    with patch(
        "newsmaker.sources.urllib.request.urlopen", return_value=_mock_urlopen(_GDELT_PAYLOAD)
    ) as urlopen:
        collector = SourceCollector()
        collector.collect("news", language="en", regions=["ZZ"])

    requested_url = urlopen.call_args.args[0].full_url
    decoded = urllib.parse.unquote_plus(requested_url)
    assert "sourcecountry:zz" in decoded


def test_country_names_param_extends_defaults_without_replacing_them():
    with patch(
        "newsmaker.sources.urllib.request.urlopen", return_value=_mock_urlopen(_GDELT_PAYLOAD)
    ) as urlopen:
        collector = SourceCollector(country_names={"PL": "poland"})
        collector.collect("news", language="en", regions=["LV", "PL"])

    requested_url = urlopen.call_args.args[0].full_url
    decoded = urllib.parse.unquote_plus(requested_url)
    assert "(sourcecountry:latvia OR sourcecountry:poland)" in decoded


def test_country_names_param_overrides_a_default_entry():
    with patch(
        "newsmaker.sources.urllib.request.urlopen", return_value=_mock_urlopen(_GDELT_PAYLOAD)
    ) as urlopen:
        collector = SourceCollector(country_names={"LV": "custom-latvia-name"})
        collector.collect("news", language="en", regions=["LV"])

    requested_url = urlopen.call_args.args[0].full_url
    decoded = urllib.parse.unquote_plus(requested_url)
    assert "sourcecountry:custom-latvia-name" in decoded
    assert "sourcecountry:latvia" not in decoded


def test_language_names_param_extends_defaults_without_replacing_them():
    collector = SourceCollector(language_names={"lv": "latvian"})

    with patch(
        "newsmaker.sources.urllib.request.urlopen", return_value=_mock_urlopen(_GDELT_PAYLOAD)
    ) as urlopen:
        collector.collect("news", language="lv")
        requested_url = urlopen.call_args.args[0].full_url
        assert "sourcelang:latvian" in urllib.parse.unquote_plus(requested_url)

        collector.collect("news", language="ru")  # built-in default still present
        requested_url = urlopen.call_args.args[0].full_url
        assert "sourcelang:russian" in urllib.parse.unquote_plus(requested_url)
