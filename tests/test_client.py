"""Tests for Client, with fake providers/collector/generator injected."""

from unittest.mock import MagicMock

import pytest

from newsmaker.client import Client
from newsmaker.exceptions import NoSourcesFoundError
from newsmaker.sources import SourceDocument


def _client(
    *, trending_result: str | None, documents: list[SourceDocument]
) -> tuple[Client, MagicMock]:
    trends_provider = MagicMock()
    trends_provider.get_trending_topic.return_value = trending_result

    source_collector = MagicMock()
    source_collector.collect.return_value = documents

    generator = MagicMock()
    generator.generate.return_value = ("Generated title", "Generated body text here.")

    client = Client(
        trends_provider=trends_provider,
        source_collector=source_collector,
        generator=generator,
        model="gpt-4o-mini",
    )
    return client, generator


def test_generate_article_assembles_result_from_matched_trend():
    documents = [SourceDocument(url="https://example.com/1", text="text")]
    client, generator = _client(trending_result="hot trend: headline", documents=documents)

    article = client.generate_article("python", 200, language="en")

    assert article.title == "Generated title"
    assert article.body == "Generated body text here."
    assert article.word_count == 4
    assert article.sources == ["https://example.com/1"]
    assert article.trending_topic == "hot trend: headline"
    assert article.provider == "openai"
    assert article.model == "gpt-4o-mini"
    generator.generate.assert_called_once_with(
        trending_topic="hot trend: headline",
        documents=documents,
        length_words=200,
        language="en",
        tone=None,
    )


def test_generate_article_falls_back_to_raw_topic_when_no_trend_found():
    documents = [SourceDocument(url="https://example.com/1", text="text")]
    client, _ = _client(trending_result=None, documents=documents)

    article = client.generate_article("niche topic", 200)

    assert article.trending_topic == "niche topic"


def test_generate_article_raises_when_no_sources_found():
    client, generator = _client(trending_result="trend", documents=[])

    with pytest.raises(NoSourcesFoundError):
        client.generate_article("python", 200)

    generator.generate.assert_not_called()


def test_requires_api_key_when_no_generator_given(monkeypatch):
    monkeypatch.delenv("NEWSMAKER_API_KEY", raising=False)

    with pytest.raises(ValueError):
        Client()


def test_reads_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("NEWSMAKER_API_KEY", "env-key")

    # Should not raise: builds a real ArticleGenerator without making a network call.
    Client()


def test_regions_are_forwarded_to_trends_and_sources():
    trends_provider = MagicMock()
    trends_provider.get_trending_topic.return_value = "trend"

    source_collector = MagicMock()
    source_collector.collect.return_value = [SourceDocument(url="https://example.com/1", text="t")]

    generator = MagicMock()
    generator.generate.return_value = ("Title", "Body.")

    client = Client(
        trends_provider=trends_provider,
        source_collector=source_collector,
        generator=generator,
    )

    client.generate_article("news", 200, language="en", regions=["LV", "LT", "EE"])

    trends_provider.get_trending_topic.assert_called_once_with(
        "news", language="en", regions=["LV", "LT", "EE"]
    )
    source_collector.collect.assert_called_once_with(
        "trend", language="en", regions=["LV", "LT", "EE"]
    )
