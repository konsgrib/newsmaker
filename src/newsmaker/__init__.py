"""newsmaker: generate an article about the currently trending angle on a topic."""

from newsmaker.client import Client
from newsmaker.exceptions import GenerationError, NewsmakerError, NoSourcesFoundError
from newsmaker.models import Article
from newsmaker.sources import (
    SerpApiSourceCollector,
    SourceCollector,
    SourceDocument,
    SourceProvider,
)
from newsmaker.trends import GoogleTrendsRssProvider, NullTrendsProvider, TrendsProvider

__all__ = [
    "Article",
    "Client",
    "GenerationError",
    "GoogleTrendsRssProvider",
    "NewsmakerError",
    "NoSourcesFoundError",
    "NullTrendsProvider",
    "SerpApiSourceCollector",
    "SourceCollector",
    "SourceDocument",
    "SourceProvider",
    "TrendsProvider",
]
