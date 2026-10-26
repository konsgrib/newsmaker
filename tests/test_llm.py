"""Tests for ArticleGenerator. Uses an injected fake OpenAI-compatible client."""

from unittest.mock import MagicMock

import pytest

from newsmaker.exceptions import GenerationError, IrrelevantSourcesError, NoSourcesFoundError
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


def test_raises_generation_error_when_fallback_title_is_too_long():
    # Malformed single-line JSON (as produced when the model breaks its own
    # "body" string with an unescaped quote): json.loads fails, so this
    # degrades to the line-split fallback, and with no newline in the
    # content the whole ~200+ char blob would become the "title". That's
    # not a usable headline, so it must fail instead of being returned.
    bogus_title = "x" * 250
    content = f'{{"title": "{bogus_title}", "body": "unterminated'
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = response

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


_TWO_DOCUMENTS = [
    SourceDocument(url="https://example.com/1", text="Car tax goes up next year."),
    SourceDocument(url="https://example.com/2", text="Taxi drivers dispute tax bills."),
]


def test_skip_response_raises_irrelevant_sources_error_without_retry():
    client = _fake_client('{"skip": true, "reason": "Sources are about taxis, not car tax."}')
    generator = ArticleGenerator(api_key="test", base_url=None, model="gpt-4o-mini", client=client)

    with pytest.raises(IrrelevantSourcesError, match="taxis, not car tax"):
        generator.generate(
            trending_topic="car tax",
            documents=_TWO_DOCUMENTS,
            length_words=100,
            language="en",
            tone=None,
        )

    # A skip is a deliberate answer, not a transient failure.
    assert client.chat.completions.create.call_count == 1


def test_irrelevant_sources_error_is_a_no_sources_found_error():
    # Callers that already handle NoSourcesFoundError (e.g. by trying
    # another topic) handle off-topic sources the same way.
    assert issubclass(IrrelevantSourcesError, NoSourcesFoundError)


def test_skip_without_reason_still_raises():
    generator = ArticleGenerator(
        api_key="test", base_url=None, model="gpt-4o-mini", client=_fake_client('{"skip": true}')
    )

    with pytest.raises(IrrelevantSourcesError, match="no reason given"):
        generator.generate(
            trending_topic="car tax",
            documents=_TWO_DOCUMENTS,
            length_words=100,
            language="en",
            tone=None,
        )


def test_skip_false_is_treated_as_a_normal_article():
    generator = ArticleGenerator(
        api_key="test",
        base_url=None,
        model="gpt-4o-mini",
        client=_fake_client('{"skip": false, "title": "Car tax", "body": "It goes up."}'),
    )

    title, body = generator.generate(
        trending_topic="car tax",
        documents=_TWO_DOCUMENTS,
        length_words=100,
        language="en",
        tone=None,
    )

    assert (title, body) == ("Car tax", "It goes up.")


def _sent_messages(client: MagicMock) -> list[dict[str, str]]:
    return client.chat.completions.create.call_args.kwargs["messages"]


def test_prompt_asks_for_relevance_check_with_minimum_of_two_sources():
    client = _fake_client('{"title": "T", "body": "B"}')
    generator = ArticleGenerator(api_key="test", base_url=None, model="gpt-4o-mini", client=client)

    generator.generate(
        trending_topic="car tax",
        documents=_TWO_DOCUMENTS,
        length_words=100,
        language="en",
        tone=None,
    )

    system, user = _sent_messages(client)
    assert '{"skip": true, "reason": "..."}' in system["content"]
    assert "Minimum number of sources about the topic: 2." in user["content"]


def test_minimum_is_capped_at_the_number_of_sources_found():
    client = _fake_client('{"title": "T", "body": "B"}')
    generator = ArticleGenerator(api_key="test", base_url=None, model="gpt-4o-mini", client=client)

    generator.generate(
        trending_topic="python", documents=_DOCUMENTS, length_words=100, language="en", tone=None
    )

    _, user = _sent_messages(client)
    assert "Minimum number of sources about the topic: 1." in user["content"]
