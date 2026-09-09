"""Tests for GoogleTrendsRssProvider. No real network access is used."""

import urllib.error
from unittest.mock import MagicMock, patch

from newsmaker.trends import GoogleTrendsRssProvider

_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0">
  <channel>
    <item>
      <title>cindy marcell blizzard</title>
      <ht:approx_traffic>200+</ht:approx_traffic>
      <ht:news_item>
        <ht:news_item_title>Remains found in Wilson County identified as missing teen
        </ht:news_item_title>
        <ht:news_item_url>https://example.com/a</ht:news_item_url>
      </ht:news_item>
    </item>
    <item>
      <title>python programming contest</title>
      <ht:approx_traffic>500+</ht:approx_traffic>
      <ht:news_item>
        <ht:news_item_title>Students win national Python coding competition</ht:news_item_title>
        <ht:news_item_url>https://example.com/b</ht:news_item_url>
      </ht:news_item>
    </item>
  </channel>
</rss>
"""


def _mock_urlopen(body: bytes):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_returns_matching_trend_with_best_headline():
    provider = GoogleTrendsRssProvider()
    with patch(
        "newsmaker.trends.urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_FEED.encode())
    ):
        result = provider.get_trending_topic("python", language="en")

    assert result == "python programming contest: Students win national Python coding competition"


def test_returns_none_when_no_trend_matches():
    provider = GoogleTrendsRssProvider()
    with patch(
        "newsmaker.trends.urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_FEED.encode())
    ):
        result = provider.get_trending_topic("quantum computing", language="en")

    assert result is None


def test_returns_none_on_empty_topic():
    provider = GoogleTrendsRssProvider()
    with patch(
        "newsmaker.trends.urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_FEED.encode())
    ) as urlopen:
        result = provider.get_trending_topic("  ", language="en")

    assert result is None
    urlopen.assert_not_called()


def test_returns_none_on_network_error():
    provider = GoogleTrendsRssProvider()
    with patch(
        "newsmaker.trends.urllib.request.urlopen",
        side_effect=urllib.error.URLError("boom"),
    ):
        result = provider.get_trending_topic("python", language="en")

    assert result is None


def test_returns_none_on_malformed_feed():
    provider = GoogleTrendsRssProvider()
    with patch("newsmaker.trends.urllib.request.urlopen", return_value=_mock_urlopen(b"not xml")):
        result = provider.get_trending_topic("python", language="en")

    assert result is None


_EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0">
  <channel></channel>
</rss>
"""


def test_regions_are_queried_in_order_until_a_match_is_found():
    def fake_urlopen(request, timeout, context):
        assert "geo=LV" in request.full_url or "geo=LT" in request.full_url
        body = _EMPTY_FEED if "geo=LV" in request.full_url else _SAMPLE_FEED
        return _mock_urlopen(body.encode())

    provider = GoogleTrendsRssProvider()
    with patch("newsmaker.trends.urllib.request.urlopen", side_effect=fake_urlopen) as urlopen:
        result = provider.get_trending_topic("python", language="en", regions=["LV", "LT", "EE"])

    assert result == "python programming contest: Students win national Python coding competition"
    # Stops at the first region with a match; EE is never queried.
    assert urlopen.call_count == 2


def test_regions_override_the_language_based_default_geo():
    with patch(
        "newsmaker.trends.urllib.request.urlopen", return_value=_mock_urlopen(_EMPTY_FEED.encode())
    ) as urlopen:
        provider = GoogleTrendsRssProvider()
        provider.get_trending_topic("python", language="en", regions=["EE"])

    requested_url = urlopen.call_args.args[0].full_url
    assert "geo=EE" in requested_url
