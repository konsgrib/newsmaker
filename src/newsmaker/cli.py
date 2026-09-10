"""Command-line entry point for manual testing.

uv run python -m newsmaker --topic "..." --length 300
"""

import argparse
import sys

from newsmaker.client import Client
from newsmaker.exceptions import NewsmakerError
from newsmaker.sources import SerpApiSourceCollector, SourceCollector, SourceProvider
from newsmaker.trends import GoogleTrendsRssProvider, NullTrendsProvider, TrendsProvider


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newsmaker",
        description="Generate an article about the currently trending angle on a topic.",
    )
    parser.add_argument("--topic", required=True, help="The topic to write about.")
    parser.add_argument(
        "--length", type=int, required=True, dest="length_words", help="Approximate word count."
    )
    parser.add_argument("--language", default="ru", help="Output language (default: ru).")
    parser.add_argument(
        "--regions",
        nargs="+",
        default=None,
        metavar="CODE",
        help="ISO 3166-1 alpha-2 country codes, e.g. --regions LV LT EE",
    )
    parser.add_argument("--tone", default=None, help="Optional free-text tone instruction.")

    parser.add_argument("--api-key", default=None, help="LLM API key (or NEWSMAKER_API_KEY).")
    parser.add_argument(
        "--base-url", default=None, help="OpenAI-compatible base URL (or NEWSMAKER_BASE_URL)."
    )
    parser.add_argument("--model", default=None, help="Model name (or NEWSMAKER_MODEL).")

    parser.add_argument(
        "--source-provider",
        choices=["gdelt", "serpapi"],
        default="gdelt",
        help="Which SourceProvider to use (default: gdelt, free but rate-limited).",
    )
    parser.add_argument(
        "--serpapi-key", default=None, help="Only used with --source-provider serpapi."
    )
    parser.add_argument("--max-sources", type=int, default=5)
    parser.add_argument(
        "--skip-trends",
        action="store_true",
        help="Skip the Google Trends lookup and use --topic as-is.",
    )
    return parser


def _build_client(args: argparse.Namespace) -> Client:
    source_collector: SourceProvider
    if args.source_provider == "serpapi":
        source_collector = SerpApiSourceCollector(
            api_key=args.serpapi_key, max_sources=args.max_sources
        )
    else:
        source_collector = SourceCollector(max_sources=args.max_sources)

    trends_provider: TrendsProvider
    trends_provider = NullTrendsProvider() if args.skip_trends else GoogleTrendsRssProvider()

    return Client(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        trends_provider=trends_provider,
        source_collector=source_collector,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        client = _build_client(args)
        article = client.generate_article(
            args.topic,
            args.length_words,
            language=args.language,
            regions=args.regions,
            tone=args.tone,
        )
    except (NewsmakerError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Trend: {article.trending_topic}")
    print(f"Sources: {', '.join(article.sources)}")
    print()
    print(article.title)
    print()
    print(article.body)
    print()
    print(f"Words: {article.word_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
