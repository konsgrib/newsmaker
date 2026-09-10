"""Tests for ArticleGenerator. Uses an injected fake OpenAI-compatible client."""

from unittest.mock import MagicMock

import pytest

from newsmaker.exceptions import GenerationError
from newsmaker.llm import ArticleGenerator
from newsmaker.sources import SourceDocument

_DOCUMENTS = [SourceDocument(url="https://example.com/1", text="Some source text.")]


def _fake_client(content: str) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = response
    return client


def test_parses_json_response():
    generator = ArticleGenerator(
        api_key="test",
        base_url=None,
        model="gpt-4o-mini",
        client=_fake_client('{"title": "JSON Title", "body": "JSON body text."}'),
    )

    title, body = generator.generate(
        trending_topic="python",
        documents=_DOCUMENTS,
        length_words=100,
        language="en",
        tone=None,
    )

    assert title == "JSON Title"
    assert body == "JSON body text."


def test_falls_back_to_line_split_when_response_is_not_json():
    generator = ArticleGenerator(
        api_key="test",
        base_url=None,
        model="gpt-4o-mini",
        client=_fake_client("Title line\nBody paragraph one."),
    )

    title, body = generator.generate(
        trending_topic="python",
        documents=_DOCUMENTS,
        length_words=100,
        language="en",
        tone=None,
    )

    assert title == "Title line"
    assert body == "Body paragraph one."


def test_falls_back_to_line_split_when_json_is_missing_a_field():
    generator = ArticleGenerator(
        api_key="test",
        base_url=None,
        model="gpt-4o-mini",
        client=_fake_client('{"title": "Only title"}'),
    )

    title, body = generator.generate(
        trending_topic="python",
        documents=_DOCUMENTS,
        length_words=100,
        language="en",
        tone=None,
    )

    # No newline in the raw content either, so the line-split fallback
    # degrades to title == body, same as any other single-line response.
    assert title == body == '{"title": "Only title"}'


def test_falls_back_to_title_as_body_when_response_has_one_line():
    generator = ArticleGenerator(
        api_key="test", base_url=None, model="gpt-4o-mini", client=_fake_client("Only one line")
    )

    title, body = generator.generate(
        trending_topic="python", documents=_DOCUMENTS, length_words=100, language="en", tone=None
    )

    assert title == "Only one line"
    assert body == "Only one line"


def test_retries_once_then_succeeds():
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="Title\nBody."))]
    client.chat.completions.create.side_effect = [RuntimeError("network error"), response]

    generator = ArticleGenerator(api_key="test", base_url=None, model="gpt-4o-mini", client=client)
    title, body = generator.generate(
        trending_topic="python", documents=_DOCUMENTS, length_words=100, language="en", tone=None
    )

    assert (title, body) == ("Title", "Body.")
    assert client.chat.completions.create.call_count == 2


def test_raises_generation_error_after_exhausting_retry():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("network error")

    generator = ArticleGenerator(api_key="test", base_url=None, model="gpt-4o-mini", client=client)

    with pytest.raises(GenerationError):
        generator.generate(
            trending_topic="python",
            documents=_DOCUMENTS,
            length_words=100,
            language="en",
            tone=None,
        )

    assert client.chat.completions.create.call_count == 2
