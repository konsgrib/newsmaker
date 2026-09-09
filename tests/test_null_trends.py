"""Tests for NullTrendsProvider."""

from newsmaker.trends import NullTrendsProvider


def test_always_returns_none():
    provider = NullTrendsProvider()

    assert provider.get_trending_topic("любая тема", language="ru") is None
    assert (
        provider.get_trending_topic("любая тема", language="ru", regions=["LV", "LT", "EE"]) is None
    )
