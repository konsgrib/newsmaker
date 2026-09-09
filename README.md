# newsmaker

Generate an article about the currently trending news angle on a topic.

Given a topic, target length, and optional tone, `newsmaker`:

1. finds the currently hottest news angle on that topic via Google Trends'
   public RSS feed (falling back to the topic itself if nothing matches);
2. gathers a handful of source articles about it (via the free GDELT API
   by default, or SerpApi as a paid alternative) and extracts their full
   text with `trafilatura`;
3. generates an article of the requested length via an OpenAI-compatible
   LLM -- OpenAI itself, or a local server such as Ollama.

It is a plain Python library, not a network service: install it directly
into the project that needs it (Django or otherwise).

## Install

Not published yet. Point a `pyproject.toml` dependency at this repository
once you are ready to wire it into a project, e.g.:

```toml
dependencies = [
    "newsmaker @ git+https://github.com/<you>/newsmaker",
]
```

## Usage

```python
from newsmaker import Client

client = Client(api_key="sk-...", model="gpt-4o-mini")

article = client.generate_article("искусственный интеллект", length_words=600)

print(article.title)
print(article.body)
print(article.sources)  # source URLs used, as metadata only
print(article.trending_topic)  # the specific trending angle chosen
```

`generate_article` is a plain, blocking call. Run it off the request/
response cycle (Celery, RQ, a management command, ...) yourself if needed.

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

Note `regions` means something different for each collector: GDELT
filters by where the source outlet is *based*; SerpApi filters by what
Google surfaces for a reader *in* that region, so e.g.
`regions=["LV", "LT", "EE"]` can legitimately return mainstream Russian
outlets that are relevant reading there, not just Baltic-published ones.

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

### Configuration

`api_key`, `base_url`, and `model` can also be supplied via the
`NEWSMAKER_API_KEY`, `NEWSMAKER_BASE_URL`, and `NEWSMAKER_MODEL`
environment variables instead of constructor arguments.
`SerpApiSourceCollector`'s `api_key` falls back to
`NEWSMAKER_SERPAPI_KEY` the same way.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests do not touch the network -- Google Trends, GDELT, and the LLM client
are mocked.
