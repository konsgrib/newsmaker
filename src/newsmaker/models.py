"""Result types returned by newsmaker."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Article:
    """A generated article and the metadata describing how it was produced."""

    title: str
    body: str
    word_count: int
    sources: list[str]
    trending_topic: str
    provider: str
    model: str
