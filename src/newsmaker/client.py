"""High-level entry point that runs the topic -> article pipeline."""

import os

from newsmaker.exceptions import NoSourcesFoundError
from newsmaker.llm import ArticleGenerator
from newsmaker.models import Article
from newsmaker.sources import SourceCollector, SourceProvider
from newsmaker.trends import GoogleTrendsRssProvider, TrendsProvider

_DEFAULT_MODEL = "gpt-4o-mini"


class Client:
    """Generates an article about the currently trending angle on a topic.

    Configuration is passed explicitly at construction time; `api_key`,
    `base_url`, and `model` fall back to the `NEWSMAKER_API_KEY`,
    `NEWSMAKER_BASE_URL`, and `NEWSMAKER_MODEL` environment variables when
    not given, so a project can also configure it purely via environment.

    To use a local, OpenAI-compatible server (e.g. Ollama) instead of
    OpenAI, pass its `base_url` (e.g. "http://localhost:11434/v1") and the
    name of the model it serves.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider_name: str = "openai",
        trends_provider: TrendsProvider | None = None,
        source_collector: SourceProvider | None = None,
        generator: ArticleGenerator | None = None,
        max_sources: int = 5,
    ) -> None:
        model = model or os.environ.get("NEWSMAKER_MODEL", _DEFAULT_MODEL)

        if generator is None:
            api_key = api_key or os.environ.get("NEWSMAKER_API_KEY")
            base_url = base_url or os.environ.get("NEWSMAKER_BASE_URL")
            if not api_key:
                raise ValueError(
                    "api_key is required (directly, via NEWSMAKER_API_KEY, "
                    "or by passing a pre-built `generator`)"
                )
            generator = ArticleGenerator(api_key=api_key, base_url=base_url, model=model)

        self._generator = generator
        self._model = model
        self._provider_name = provider_name
        self._trends_provider = trends_provider or GoogleTrendsRssProvider()
        self._source_collector = source_collector or SourceCollector(max_sources=max_sources)

    def generate_article(
        self,
        topic: str,
        length_words: int,
        *,
        language: str = "ru",
        regions: list[str] | None = None,
        tone: str | None = None,
    ) -> Article:
        """Generate an article about the currently trending angle on `topic`.

        `regions` restricts both trend detection and source discovery to
        the given ISO 3166-1 alpha-2 country codes (e.g. `["LV", "LT",
        "EE"]`). When omitted, `language` alone picks a default region.

        Raises NoSourcesFoundError if no usable source articles could be
        found or extracted, and GenerationError if the LLM call fails after
        one retry.
        """
        trending_topic = (
            self._trends_provider.get_trending_topic(topic, language=language, regions=regions)
            or topic
        )

        documents = self._source_collector.collect(
            trending_topic, language=language, regions=regions
        )
        if not documents:
            raise NoSourcesFoundError(
                f"No usable source articles were found for {trending_topic!r}"
            )

        title, body = self._generator.generate(
            trending_topic=trending_topic,
            documents=documents,
            length_words=length_words,
            language=language,
            tone=tone,
        )

        return Article(
            title=title,
            body=body,
            word_count=len(body.split()),
            sources=[document.url for document in documents],
            trending_topic=trending_topic,
            provider=self._provider_name,
            model=self._model,
        )
