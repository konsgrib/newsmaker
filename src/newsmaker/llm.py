"""Article generation via an OpenAI-compatible chat completions API.

Works against OpenAI itself or any locally hosted server that exposes the
same API (e.g. Ollama's `/v1/chat/completions`) -- the only difference is
the `base_url`/`api_key` passed in.
"""

import json
import logging
from datetime import date

from openai import OpenAI

from newsmaker.exceptions import GenerationError, IrrelevantSourcesError
from newsmaker.sources import SourceDocument

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a news article writer. Write a clear, factual article based "
    "only on the source material you are given. Do not invent facts that "
    "are not supported by the sources. Do not cite, link to, or mention "
    "the sources by name inside the article. Respond with only a single "
    'JSON object of the form {"title": "...", "body": "..."} -- no '
    "markdown, no code fences, no text before or after it.\n\n"
    "Source search is keyword-based, so some sources may only share a word "
    "with the topic without being about it. First decide which sources are "
    "actually about the topic, and write the article from those alone. If "
    "fewer of them are about the topic than the minimum stated in the "
    "request, do not write an article; respond instead with only "
    '{"skip": true, "reason": "..."}, giving a short reason.\n\n'
    "The request states today's date and, where known, each source's "
    "publication date. Write about what the sources report as recent: "
    "events, decisions and changes from around their publication date. "
    "Older rules or events mentioned as background may be given as "
    "context, with their dates, but never present them as new."
)

# Fewer on-topic sources than this (or than the number of sources given,
# when fewer were found) means there is no real story to write about.
_MIN_RELEVANT_SOURCES = 2

# Keeps the prompt (and cost/context usage) bounded regardless of how much
# text trafilatura extracted from a given source page.
_MAX_SOURCE_CHARS = 4000

# One retry covers a transient network/API error without adding a retry loop.
_MAX_ATTEMPTS = 2

# A real headline is well under this. A single-line fallback response at or
# above it usually means the model's JSON was malformed (e.g. an unescaped
# quote broke the "body" string) and _split_title_and_body grabbed the whole
# response as the "title" -- that's not a usable article, so it's treated as
# a failed generation rather than returned as-is.
_MAX_TITLE_CHARS = 200


class ArticleGenerator:
    """Generates an article title and body from a topic and source material."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        client: OpenAI | None = None,
    ) -> None:
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def generate(
        self,
        *,
        trending_topic: str,
        documents: list[SourceDocument],
        length_words: int,
        language: str,
        tone: str | None,
    ) -> tuple[str, str]:
        """Return (title, body) for the generated article.

        Raises IrrelevantSourcesError (not retried) if the model reports
        that too few sources are about the topic, and GenerationError if
        the request fails on both attempts.
        """
        prompt = self._build_prompt(
            trending_topic=trending_topic,
            documents=documents,
            length_words=length_words,
            language=language,
            tone=tone,
        )

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._complete(prompt)
            except IrrelevantSourcesError:
                # A deliberate answer about the sources, not a failure --
                # asking again would only cost another call.
                raise
            except Exception as exc:  # noqa: BLE001 - retried once, then wrapped below
                logger.warning(
                    "LLM call failed on attempt %d/%d: %s", attempt + 1, _MAX_ATTEMPTS, exc
                )
                last_error = exc
        raise GenerationError(f"LLM generation failed after retry: {last_error}") from last_error

    def _complete(self, prompt: str) -> tuple[str, str]:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        self._raise_if_skipped(content)
        title, body = self._parse_json(content) or self._split_title_and_body(content)
        if not title or not body or len(title) > _MAX_TITLE_CHARS:
            raise ValueError(
                f"model response did not yield a usable title/body (title length={len(title)})"
            )
        return title, body

    @staticmethod
    def _raise_if_skipped(content: str) -> None:
        """Raise IrrelevantSourcesError for a `{"skip": true, ...}` response."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return
        if isinstance(data, dict) and data.get("skip") is True:
            reason = str(data.get("reason") or "").strip() or "no reason given"
            logger.warning("model skipped the article, sources are off-topic: %s", reason)
            raise IrrelevantSourcesError(reason)

    @staticmethod
    def _parse_json(content: str) -> tuple[str, str] | None:
        """Parse a `{"title": ..., "body": ...}` response, if the model produced one.

        Not all OpenAI-compatible servers/models reliably follow the JSON
        instruction in the prompt (no `response_format` API parameter is
        used here, since support for it varies across local servers) --
        this returns None rather than raising when parsing doesn't pan
        out, so the caller can fall back to the plain-text convention.
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        title, body = data.get("title"), data.get("body")
        if not isinstance(title, str) or not isinstance(body, str) or not title or not body:
            return None
        return title.strip(), body.strip()

    @staticmethod
    def _split_title_and_body(content: str) -> tuple[str, str]:
        """Fallback for a model that ignored the JSON instruction: treat the first
        line as the title and the rest as the body."""
        logger.debug("response was not the expected JSON shape, falling back to line-split parsing")
        first_line, _, rest = content.strip().partition("\n")
        title = first_line.lstrip("#").strip()
        body = rest.strip()
        return (title, body) if body else (title, title)

    @staticmethod
    def _build_prompt(
        *,
        trending_topic: str,
        documents: list[SourceDocument],
        length_words: int,
        language: str,
        tone: str | None,
    ) -> str:
        sources_block = "\n\n".join(
            f"Source {index}{_published_label(document)}:\n{document.text[:_MAX_SOURCE_CHARS]}"
            for index, document in enumerate(documents, start=1)
        )
        tone_line = f"Tone: {tone}\n" if tone else ""
        min_relevant = min(_MIN_RELEVANT_SOURCES, len(documents))
        return (
            f"Today's date: {date.today().isoformat()}\n"
            f"Topic: {trending_topic}\n"
            f"Language: {language}\n"
            f"{tone_line}"
            f"Target length: approximately {length_words} words.\n"
            f"Minimum number of sources about the topic: {min_relevant}.\n\n"
            "Write a news article based on the sources below and return "
            "it as the JSON object described in your instructions.\n\n"
            f"{sources_block}"
        )


def _published_label(document: SourceDocument) -> str:
    return f" (published {document.published.isoformat()})" if document.published else ""
