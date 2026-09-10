# newsmaker

Repository: https://github.com/konsgrib/newsmaker (private)

Generate an article about the currently trending news angle on a topic.

Given a topic, target length, and optional tone, `newsmaker`:

1. finds the currently hottest news angle on that topic via Google Trends'
   public RSS feed (falling back to the topic itself if nothing matches,
   which is the common case for evergreen topics -- see
   [Skipping the Google Trends step](#skipping-the-google-trends-step));
2. gathers a handful of source articles about it (via the free GDELT API
   by default, or SerpApi as a paid alternative) and extracts their full
   text with `trafilatura`;
3. generates an article of the requested length via an OpenAI-compatible
   LLM -- OpenAI itself, or a local server such as Ollama.

It is a plain Python library, not a network service: install it directly
into the project that needs it (Django or otherwise). It has no database,
no task queue, and no built-in async API -- `generate_article` is a
single blocking call, and running it off the request/response cycle
(Celery, RQ, a management command, ...) is the calling project's job.

## Install

Not published to PyPI. Point a `pyproject.toml` dependency at this
(private) repository once you are ready to wire it into a project, e.g.:

```toml
dependencies = [
    "newsmaker @ git+https://github.com/konsgrib/newsmaker",
]
```

The repository is private, so the consuming project's environment needs
Git credentials for `github.com/konsgrib` (SSH key or a `gh`-authenticated
HTTPS credential helper) to install it this way.

## Quick start

```python
from newsmaker import Client

client = Client(api_key="sk-...", model="gpt-4o-mini")

article = client.generate_article("искусственный интеллект", length_words=600)

print(article.title)
print(article.body)
print(article.word_count)  # actual word count of the generated body
print(article.sources)  # source URLs used, as metadata only -- the
# body itself never cites or links to them
print(article.trending_topic)  # the specific trending angle chosen, or
# the topic itself if nothing was trending
print(article.provider)  # "openai" by default
print(article.model)  # the model name that generated it
```

A more complete example, restricted to a specific region and skipping the
Google Trends lookup (see the sections below for why you'd want either):

```python
from newsmaker import Client, NullTrendsProvider, SerpApiSourceCollector

client = Client(
    api_key="sk-...",
    model="gpt-4o-mini",
    trends_provider=NullTrendsProvider(),
    source_collector=SerpApiSourceCollector(api_key="serpapi-key"),
)

article = client.generate_article(
    "ошибки начинающих водителей",
    length_words=250,
    language="ru",
    regions=["LV", "LT", "EE"],
    tone="нейтральный, информативный",
)
```

## Options

### Restricting to specific regions

Pass `regions` as a list of ISO 3166-1 alpha-2 country codes to restrict
both trend detection and source discovery to those countries (instead of
the single default region `language` picks):

```python
article = client.generate_article(
    "искусственный интеллект",
    length_words=600,
    regions=["LV", "LT", "EE"],
)
```

`regions` behaves slightly differently depending on the active
`source_collector` -- see
[Using SerpApi instead of GDELT](#using-serpapi-instead-of-gdelt-for-source-discovery).

### Skipping the Google Trends step

For evergreen topics that rarely show up as an actual Google Trends
"trending search" (e.g. road safety, driving lessons), every real lookup
just falls back to the raw topic anyway. Pass `NullTrendsProvider` to skip
the network call entirely:

```python
from newsmaker import Client, NullTrendsProvider

client = Client(
    api_key="sk-...",
    model="gpt-4o-mini",
    trends_provider=NullTrendsProvider(),
)
```

### Using SerpApi instead of GDELT for source discovery

GDELT (the default) is free and needs no account, but enforces an
aggressive, undocumented rate limit on unauthenticated callers -- under
sustained use it can return HTTP 429 for extended periods, even from an
IP that never called it before. If that makes it unusable, swap in
`SerpApiSourceCollector`, a paid alternative with the same interface
(get a key at https://serpapi.com/; free tier available, no card
required):

```python
from newsmaker import Client, SerpApiSourceCollector

client = Client(
    api_key="sk-...",
    model="gpt-4o-mini",
    source_collector=SerpApiSourceCollector(api_key="serpapi-key"),
)
```

For `regions` values with no native "filter by outlet's country" option
(unlike GDELT's `sourcecountry:`), `SerpApiSourceCollector` restricts
results to a small built-in list of major regional outlets via a `site:`
filter -- currently covering `LV`, `LT`, and `EE`. A region missing from
that list falls back to `gl`/`hl`-only targeting, which picks what's
relevant to a reader *in* that region rather than what's *published*
there -- e.g. mainstream Russian national outlets, not just local ones.

Extend or override that built-in list with `region_domains` (merged per
region key, not a full replacement):

```python
source_collector = SerpApiSourceCollector(
    api_key="serpapi-key",
    region_domains={"PL": ["example-outlet.pl"]},  # adds PL, keeps LV/LT/EE
)
```

`SerpApiSourceCollector`'s `api_key` also falls back to the
`NEWSMAKER_SERPAPI_KEY` environment variable.

### Using a local model

Point `base_url` at any OpenAI-compatible server, e.g. Ollama:

```python
client = Client(
    api_key="ollama",  # ignored by Ollama, but required by the SDK
    base_url="http://localhost:11434/v1",
    model="llama3.1",
)
```

The prompt asks for a `{"title": ..., "body": ...}` JSON response, which
is parsed directly when the model complies. Smaller local models are more
likely to ignore that and just write prose; when that happens, parsing
falls back to treating the first line as the title -- and if there's no
line break either, `Article.title` and `Article.body` end up identical
rather than the call failing. Larger models (tested: `qwen3` family)
follow the JSON instruction reliably.

## Command line

For manual testing without writing a script each time:

```bash
uv run python -m newsmaker \
    --topic "ошибки начинающих водителей" \
    --length 250 \
    --language ru \
    --regions LV LT EE \
    --skip-trends \
    --source-provider serpapi --serpapi-key "$SERPAPI_KEY" \
    --api-key ollama --base-url http://localhost:11434/v1 --model qwen3.8:27b-mlx
```

Or, once installed into a project's environment, the shorter `newsmaker
--topic ... --length ...` (see `[project.scripts]` in `pyproject.toml`).
Run `newsmaker --help` (or `python -m newsmaker --help`) for the full
option list -- it mirrors `generate_article`'s parameters plus
`--skip-trends` (uses `NullTrendsProvider`) and `--source-provider
{gdelt,serpapi}`.

## Logging

Each module logs under `newsmaker.*` via the standard `logging` module
(e.g. `newsmaker.sources`, `newsmaker.client`) -- rate limits, failed
requests, extraction failures, trend matches, and retries. The package
never calls `logging.basicConfig()` itself (a library shouldn't configure
global logging); without any handler configured, Python's default
"last resort" handler still prints `WARNING`-and-above to stderr, which
is why CLI runs show messages like `GDELT rate-limited us (429)...` with
no setup. Configure handlers/levels for the `newsmaker` logger in your
own application to see `INFO`/`DEBUG` messages too.

## Errors

- `NoSourcesFoundError` -- no usable source articles were found or could
  be extracted for the topic. Zero sources is the only source-related
  failure; 1-4 (instead of up to 5) is not an error.
- `GenerationError` -- the LLM call failed on both the initial attempt and
  one automatic retry.

A missing Google Trends match is not an error: `generate_article` silently
falls back to the raw topic.

## Configuration

`api_key`, `base_url`, and `model` can also be supplied via environment
variables instead of constructor arguments:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEWSMAKER_API_KEY` | none | LLM API key (OpenAI, or ignored by most local servers). |
| `NEWSMAKER_BASE_URL` | OpenAI's default | Base URL of the OpenAI-compatible chat completions endpoint. |
| `NEWSMAKER_MODEL` | `gpt-4o-mini` | Model name to request. |
| `NEWSMAKER_SERPAPI_KEY` | none | API key for `SerpApiSourceCollector` (unused by the default GDELT-based collector). |

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests do not touch the network -- Google Trends, GDELT, SerpApi, and the
LLM client are all mocked.
