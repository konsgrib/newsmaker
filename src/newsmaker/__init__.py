"""newsmaker: generate an article about the currently trending angle on a topic."""

from newsmaker.client import Client
from newsmaker.exceptions import (
    GenerationError,
    IrrelevantSourcesError,
    NewsmakerError,
    NoSourcesFoundError,
)
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
    "IrrelevantSourcesError",
    "NewsmakerError",
    "NoSourcesFoundError",
    "NullTrendsProvider",
    "SerpApiSourceCollector",
    "SourceCollector",
    "SourceDocument",
    "SourceProvider",
    "TrendsProvider",
]
