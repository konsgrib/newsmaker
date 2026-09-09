"""Article generation via an OpenAI-compatible chat completions API.

Works against OpenAI itself or any locally hosted server that exposes the
same API (e.g. Ollama's `/v1/chat/completions`) -- the only difference is
the `base_url`/`api_key` passed in.
"""

from openai import OpenAI

from newsmaker.exceptions import GenerationError
from newsmaker.sources import SourceDocument

_SYSTEM_PROMPT = (
    "You are a news article writer. Write a clear, factual article based "
    "only on the source material you are given. Do not invent facts that "
    "are not supported by the sources. Do not cite, link to, or mention "
    "the sources by name inside the article."
)

# Keeps the prompt (and cost/context usage) bounded regardless of how much
# text trafilatura extracted from a given source page.
_MAX_SOURCE_CHARS = 4000

# One retry covers a transient network/API error without adding a retry loop.
_MAX_ATTEMPTS = 2


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

        Raises GenerationError if the request fails on both attempts.
        """
        prompt = self._build_prompt(
            trending_topic=trending_topic,
            documents=documents,
            length_words=length_words,
            language=language,
            tone=tone,
        )

        last_error: Exception | None = None
        for _attempt in range(_MAX_ATTEMPTS):
            try:
                return self._complete(prompt)
            except Exception as exc:  # noqa: BLE001 - retried once, then wrapped below
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
        return self._split_title_and_body(content)

    @staticmethod
    def _split_title_and_body(content: str) -> tuple[str, str]:
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
            f"Source {index}:\n{document.text[:_MAX_SOURCE_CHARS]}"
            for index, document in enumerate(documents, start=1)
        )
        tone_line = f"Tone: {tone}\n" if tone else ""
        return (
            f"Topic: {trending_topic}\n"
            f"Language: {language}\n"
            f"{tone_line}"
            f"Target length: approximately {length_words} words.\n\n"
            "Write a news article based on the sources below. The first "
            "line must be the article title only, with no markdown "
            "formatting. Everything after that is the article body.\n\n"
            f"{sources_block}"
        )
