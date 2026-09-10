"""Tests for the CLI argument parsing and client wiring. No network access."""

from newsmaker.cli import _build_arg_parser, _build_client, main
from newsmaker.sources import SerpApiSourceCollector, SourceCollector
from newsmaker.trends import GoogleTrendsRssProvider, NullTrendsProvider


def test_parses_required_args():
    args = _build_arg_parser().parse_args(["--topic", "python", "--length", "300"])

    assert args.topic == "python"
    assert args.length_words == 300
    assert args.language == "ru"
    assert args.regions is None
    assert args.source_provider == "gdelt"
    assert args.skip_trends is False


def test_parses_regions_as_a_list():
    args = _build_arg_parser().parse_args(
        ["--topic", "x", "--length", "100", "--regions", "LV", "LT", "EE"]
    )

    assert args.regions == ["LV", "LT", "EE"]


def test_build_client_defaults_to_gdelt_and_real_trends():
    args = _build_arg_parser().parse_args(["--topic", "x", "--length", "100", "--api-key", "k"])

    client = _build_client(args)

    assert isinstance(client._source_collector, SourceCollector)
    assert isinstance(client._trends_provider, GoogleTrendsRssProvider)


def test_build_client_uses_serpapi_when_requested():
    args = _build_arg_parser().parse_args(
        [
            "--topic",
            "x",
            "--length",
            "100",
            "--api-key",
            "k",
            "--source-provider",
            "serpapi",
            "--serpapi-key",
            "serp-key",
        ]
    )

    client = _build_client(args)

    assert isinstance(client._source_collector, SerpApiSourceCollector)


def test_build_client_uses_null_trends_when_skip_trends_set():
    args = _build_arg_parser().parse_args(
        ["--topic", "x", "--length", "100", "--api-key", "k", "--skip-trends"]
    )

    client = _build_client(args)

    assert isinstance(client._trends_provider, NullTrendsProvider)


def test_main_prints_error_and_returns_1_without_raising(monkeypatch, capsys):
    monkeypatch.delenv("NEWSMAKER_API_KEY", raising=False)

    exit_code = main(["--topic", "x", "--length", "100"])

    assert exit_code == 1
    assert "error" in capsys.readouterr().err.lower()
