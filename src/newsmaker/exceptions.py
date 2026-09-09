"""Exceptions raised by the newsmaker package."""


class NewsmakerError(Exception):
    """Base class for all newsmaker errors."""


class NoSourcesFoundError(NewsmakerError):
    """Raised when no usable source articles could be found or extracted for the topic."""


class GenerationError(NewsmakerError):
    """Raised when the LLM failed to produce an article after the configured retry."""
