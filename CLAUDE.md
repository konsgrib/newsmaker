# CLAUDE.md

## Project

`newsmaker` is a small, educational Python library (not a network service)
that generates an article about the currently trending news angle on a
given topic. It is meant to be installed directly into other projects
(mostly Django) as a dependency, not run standalone.

Given a topic, target length, and optional tone/language, the library:

1. finds the currently hottest news angle on that topic via Google Trends'
   public RSS feed;
2. gathers a handful of source articles about it (via the free GDELT API
   by default, or SerpApi as a paid `SourceProvider` alternative) and
   extracts their full text;
3. generates an article of the requested length/tone via an
   OpenAI-compatible LLM (OpenAI itself, or a local server such as Ollama).

Prefer the simplest solution that satisfies the requirements.

Do not introduce architectural patterns, abstractions, services, databases,
or infrastructure unless they are explicitly required by the task. In
particular: this project has no network service, no task queue, and no
database — the calling project owns those concerns.

## Technology Stack

* Python 3.14
* `openai` (LLM calls, against OpenAI or any OpenAI-compatible local server)
* `trafilatura` (source article text extraction)
* pytest
* uv
* Ruff

Use the Python standard library where possible. `urllib`/`xml.etree` are
used directly for the Google Trends RSS feed and the GDELT API instead of
adding an HTTP client dependency; `argparse` for the CLI; `logging` for
diagnostics; `concurrent.futures.ThreadPoolExecutor` for the (I/O-bound)
parallel source-extraction step. None of these need a dependency.

Do not introduce a dependency when the required functionality can be
implemented cleanly with the standard library.

## Project Structure

```text
src/
└── newsmaker/
    ├── __init__.py     # public exports
    ├── client.py       # Client: wires trends -> sources -> llm together
    ├── trends.py       # TrendsProvider protocol + Google Trends RSS impl
    ├── sources.py       # SourceProvider protocol + GDELT/SerpApi impls + extraction
    ├── llm.py          # ArticleGenerator (OpenAI-compatible chat API)
    ├── models.py        # Article result dataclass
    ├── exceptions.py    # NewsmakerError and subclasses
    ├── cli.py           # `python -m newsmaker` / installed `newsmaker` command
    └── __main__.py       # thin `python -m newsmaker` entry point

tests/

pyproject.toml
```

Keep the pipeline stages (trends, sources, llm) in separate modules.
`Client` in `client.py` is the only place that wires them together; it
should stay orchestration-only, with no HTTP or parsing logic of its own.

Do not introduce additional architectural layers unless they are required
by the task.

## Development Rules

* Use Python 3.14.
* Follow modern Python practices.
* Use type hints.
* Prefer small, focused functions.
* Keep the implementation simple.
* Avoid unnecessary abstractions.
* Avoid unnecessary dependencies.
* Preserve existing behavior unless the task explicitly requires a change.
* When existing behavior changes, update or add appropriate tests.
* Every new feature must have appropriate tests.
* Do not modify or remove tests merely to make them pass.
* Do not make unrelated changes while implementing a task.
* Do not commit secrets, credentials, `.env` files, or other sensitive
  configuration.

## Dependency Management

Use `uv` for Python dependency management and running project commands.

Do not use `pip` directly for project dependency management.

Dependencies must be declared in `pyproject.toml`.

Do not add a dependency merely for convenience when the standard library
or an existing project dependency provides a clean solution.

## Testing

Use pytest for testing.

Run the test suite with:

```bash
uv run pytest
```

Tests must not depend on network access. Mock `urllib.request.urlopen`,
`trafilatura.fetch_url`/`extract`, and the injected OpenAI-compatible
client rather than calling the real Google Trends feed, GDELT API, or an
LLM provider.

Tests should cover:

* normal successful behavior;
* invalid input;
* important edge cases (no trend found, too few/no sources, LLM failure).

Every new feature should include appropriate tests.

Do not weaken, remove, or rewrite tests merely to make them pass.

If a test exposes a genuine change in expected behavior, update the
implementation and the test intentionally.

## Code Quality

Use Ruff for linting and formatting.

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Code must pass Ruff checks before a task can be considered complete.

Do not disable or ignore a Ruff rule merely to make checks pass.

If a rule genuinely needs to be disabled, document the specific technical
reason.

## Public API

`newsmaker.Client(api_key=..., base_url=..., model=...).generate_article(
topic, length_words, language="ru", regions=None, tone=None) -> Article`

* `api_key`, `base_url`, and `model` are explicit constructor arguments,
  with `NEWSMAKER_API_KEY` / `NEWSMAKER_BASE_URL` / `NEWSMAKER_MODEL`
  environment variables as a fallback. Do not add Django-specific
  settings integration — the package must stay usable from any Python
  project.
* To use a local model, pass `base_url` pointing at an OpenAI-compatible
  server (e.g. `http://localhost:11434/v1` for Ollama) and that server's
  model name.
* `generate_article` is a plain synchronous call. Running it off the
  request/response cycle (Celery, RQ, a management command, etc.) is the
  calling project's responsibility, not this package's.
* `regions` is an explicit, optional list of ISO 3166-1 alpha-2 country
  codes (e.g. `["LV", "LT", "EE"]`) that restricts both trend detection
  (queried region by region, in list order, first match wins) and source
  discovery (GDELT `sourcecountry:` OR-filter). It is never hardcoded —
  a caller that only cares about one market always passes it explicitly.
  When omitted, `language` alone picks a single default region, same as
  before `regions` existed.
* Length is approximate and measured in words, not a strict limit.
* Sources are returned as metadata only (`Article.sources`); the article
  body must not cite or link to them.
* `NoSourcesFoundError` is raised when zero usable sources were found;
  `GenerationError` is raised when the LLM call fails after one retry.
  Both are soft-degradation boundaries, not the only failure points —
  a missing trend match or 1-4 (rather than 5) sources are not errors.
* `trends_provider` accepts anything satisfying the `TrendsProvider`
  protocol. The default, `GoogleTrendsRssProvider`, matches `topic`
  against Google's trending-searches RSS feed. `NullTrendsProvider` is a
  no-op alternative (always signals no match, skipping the network call)
  for evergreen topic domains where a real trending match would rarely
  happen anyway — the pipeline's existing soft-degradation fallback
  (use the raw topic) makes this a genuine no-op, not a workaround.
* `source_collector` accepts anything satisfying the `SourceProvider`
  protocol. The default, `SourceCollector`, uses GDELT (free, no key,
  but rate-limits unauthenticated callers hard and unpredictably —
  observed multi-hour 429s against both a stale IP and a brand new one
  during development). `SerpApiSourceCollector` is a paid drop-in
  alternative (same interface) for when that makes GDELT unusable.
  `SerpApiSourceCollector` has no native "outlet's country" filter like
  GDELT's `sourcecountry:` (`gl`/`hl` alone only target the Google News
  *audience* — confirmed live that `regions=["LV","LT","EE"]` with just
  `gl` returned mainstream Russian outlets, not Baltic-based ones, which
  turned out not to be what was wanted). So for `regions` values covered
  by its (built-in + caller-supplied, merged) region-domains map
  (currently `LV`/`LT`/`EE` by default), it restricts results with a
  `site:` OR-filter over a small curated list of major regional outlets,
  matching GDELT's source-country semantics. A region missing from that
  map silently falls back to `gl`/`hl`-only (audience) targeting.
  `SerpApiSourceCollector(region_domains={...})` extends/overrides the
  built-in map per region key rather than replacing it outright — prefer
  that over relying on the audience-only fallback when precise filtering
  matters for a new region.
* Both `SourceCollector` and `SerpApiSourceCollector` extract candidate
  URLs' text concurrently (`concurrent.futures.ThreadPoolExecutor`,
  shared `_extract_documents` helper in `sources.py`) and stop once
  `max_sources` documents have succeeded, cancelling not-yet-started
  extractions rather than waiting for them. This is purely an
  implementation detail -- `collect()`'s signature and return order
  (matching candidate order, not completion order) are unchanged. Tests
  that mock `trafilatura.fetch_url`/`extract` per-URL must key
  `side_effect` off the URL argument, not off call order — a positional
  `side_effect` list is not safe to consume from multiple threads.
* `ArticleGenerator` asks the LLM for a `{"title": ..., "body": ...}`
  JSON response (in the prompt text only — no `response_format` API
  parameter, since support for it isn't guaranteed across arbitrary
  OpenAI-compatible servers) and parses that first. If parsing fails
  (model ignored the instruction), it falls back to the original
  "first line is the title" convention. This is strictly a more
  permissive fallback chain, not a behavior change for models that
  already didn't respect the old convention.
* All modules log under `newsmaker.*` via the standard `logging` module
  (per-module `logging.getLogger(__name__)`); the package never calls
  `logging.basicConfig()` itself. Don't add print statements for
  diagnostics — use `logger.debug`/`.info`/`.warning` instead, matching
  the existing level conventions (`debug` for expected/routine misses,
  `warning` for failures worth a human's attention, `info` for
  client.py's top-level pipeline trace).
* `python -m newsmaker` / the installed `newsmaker` command (`cli.py`,
  `[project.scripts]` in `pyproject.toml`) is for manual testing, not a
  supported integration surface for calling projects — those should
  import `Client` directly.

Preserve this contract unless a task explicitly requires changing it.

## Git

Use Git for version control.

Keep commits focused and logically grouped.

Do not rewrite existing commit history unless explicitly requested.

Do not commit generated files, local virtual environments, caches,
secrets, or files that should be ignored.

Before creating a commit:

1. Check the changed files.
2. Run the relevant tests.
3. Run Ruff checks.
4. Review the final diff.

Do not create a Git commit unless the task explicitly requires a commit
or the user has authorized committing the completed work.

Do not push changes to a remote repository unless explicitly authorized.

## Configuration

Application configuration should be provided through environment variables
or explicit constructor arguments when configuration genuinely needs to
vary between environments (see Public API above).

Do not hard-code secrets or environment-specific configuration into
source code.

Do not commit `.env` files containing real secrets.

### Supported environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEWSMAKER_API_KEY` | none | API key for the LLM provider (OpenAI, or ignored by most local servers). |
| `NEWSMAKER_BASE_URL` | OpenAI's default | Base URL of the OpenAI-compatible chat completions endpoint. |
| `NEWSMAKER_MODEL` | `gpt-4o-mini` | Model name to request. |
| `NEWSMAKER_SERPAPI_KEY` | none | API key for `SerpApiSourceCollector` (unused by the default GDELT-based collector). |

## Working Style

When implementing a task:

1. Inspect the existing project structure and relevant code first.
2. Understand the existing implementation before making changes.
3. Identify relevant constraints from this file.
4. Create a concise implementation plan.
5. For larger tasks, break the work into small, independently verifiable
   steps.
6. Keep the project in a runnable state whenever practical.
7. Implement the smallest reasonable change.
8. Add or update tests.
9. Run the relevant tests.
10. Investigate and fix failures before continuing.
11. Run the applicable code-quality checks.
12. Review the final Git diff.
13. Only then report the task as complete.

Do not stop after writing code.

Do not skip verification merely because the implementation appears
correct.

Do not make unrelated improvements unless they are necessary to complete
the requested task or prevent a concrete defect.

## Definition of Done

A task is considered complete only when all applicable criteria below
have been verified with actual execution results.

1. The requested functionality has been implemented.
2. Appropriate tests have been added or updated.
3. All relevant tests pass (`uv run pytest`).
4. Ruff linting and formatting checks pass.
5. No unnecessary dependencies have been introduced.
6. No unrelated changes have been introduced.
7. The final Git diff has been reviewed.

Never report a task as complete based only on code inspection or expected
behavior when it can instead be verified by actually running the tests
and checks above.
