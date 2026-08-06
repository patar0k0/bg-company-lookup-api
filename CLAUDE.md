# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup (Windows; venv already exists at .venv)
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env   # fill in COMPANYBOOK_API_KEY, SITE_ACCESS_TOKEN, GEMINI_API_KEY

# Tests
pytest                              # full suite
pytest tests/test_api.py -v         # one file
pytest tests/test_api.py -v -k report   # tests matching a keyword (e.g. all /api/report tests)

# Lint / format
ruff check .
ruff format .

# Run locally
python -m bg_company_lookup.api                 # Flask dev server on $PORT (default 5000)
python -m bg_company_lookup.cli 106590295        # CLI lookup by EIK or name
python -m bg_company_lookup.cli "Декорамет ЕООД" --json

# Production (Linux only, gunicorn not installed on Windows — see [prod] extra)
pip install -e ".[prod]"
gunicorn -w 2 -b 0.0.0.0:5000 "bg_company_lookup.api:app"
```

Tests never hit real upstream APIs — `test_core.py`/`test_api.py` mock `requests`/`bg_company_lookup.api.lookup`, `test_research.py`/`test_api.py` mock `bg_company_lookup.research.genai.Client` / `bg_company_lookup.api.research`.

## Architecture

`src/bg_company_lookup/` is a src-layout package with three logic-owning modules and one thin Flask wrapper:

- **`core.py`** — `lookup(name_or_eik)` wraps the companybook.bg registry API (`COMPANYBOOK_API_KEY`). Resolves a company name to an EIK via `/search` if the query isn't already EIK-shaped, then fetches the full profile + optional financials. Raises `CompanyNotFound` (404-equivalent) or `LookupServiceError` (upstream down); missing API key raises plain `RuntimeError`.
- **`research.py`** — mirrors `core.py`'s shape exactly (plain functions + one `RuntimeError`-for-missing-key / `ResearchServiceError`-for-upstream-down pair). Wraps the Gemini API (`google-genai` SDK, `GEMINI_API_KEY`, primary model configurable via `GEMINI_MODEL`, default `gemini-3.5-flash-lite`). Four functions: `research(query)` does a Google Search–grounded summary; `find_addresses(query)` does a separate Google Search–grounded call asking specifically for all known physical addresses of the company, parsed from the model's JSON response (invalid JSON degrades to an empty list rather than raising); `merge_addresses(official_data, web_result)` is a pure function reconciling `core.lookup()`'s registry addresses with `find_addresses()`'s web results, flagging web addresses that don't match any registry address; `cross_check(query, official_data, research_answer)` sends both `core.lookup()`'s output and `research()`'s output to Gemini with a fixed prompt that explicitly flags web claims unconfirmed by the official registry. Both route through `_generate_with_fallback()`, which walks `_model_chain()` (configured model, then `FALLBACK_MODELS` in order) and only advances to the next model on a `google.genai.errors.APIError` with `.code == 429` (quota exhausted) — any other error fails immediately without trying further models. Added because a shared `GEMINI_API_KEY` across projects can exhaust one model's quota while others still have headroom.
- **`cache.py`** — `TTLCache`: minimal thread-safe in-memory dict + lock, no eviction beyond lazy expiry-on-read. Not shared across gunicorn worker processes (`-w 2`) — each worker has its own copy, an accepted trade-off for this low-traffic personal tool over adding a shared store (Redis etc.).
- **`api.py`** — `create_app(access_token, report_cache_ttl_seconds=REPORT_CACHE_TTL_SECONDS)` builds the Flask app. All three routes share one auth/validation model: `token` query param checked against `SITE_ACCESS_TOKEN` (401 if configured and wrong/missing), `q` query param required and length-capped at `MAX_QUERY_LENGTH` (400). The two newer routes (`/api/research`, `/api/report`) share a `_validate_request()` helper for this; `/api/company` still does it inline (kept that way deliberately so its behavior is untouched by future edits). Every route maps its module's typed exceptions to HTTP status the same way: missing-key `RuntimeError` → 500, upstream-error type → 502 (logged via `app.logger.error`), unexpected `Exception` → 502 with a logged stack trace (never leaked to the client). `/api/report` calls `core.lookup()`, `research.research()`, and `research.find_addresses()` **concurrently** via `ThreadPoolExecutor` (none of the three depend on each other; `cross_check()` needs `lookup()`+`research()`'s results, `merge_addresses()` needs `lookup()`+`find_addresses()`'s results) to cut latency and reduce the risk of hitting Render's gateway timeout — trade-off: `research()` and `find_addresses()` now run even when `lookup()` fails first, instead of being skipped. `CompanyNotFound` from `lookup()` is a soft degrade (continues with `official_data: None`); every other failure in the chain is fail-closed (no silent partial reports). Successful `/api/report` responses are cached in a fresh `TTLCache` per `create_app()` call, keyed on `q.strip().lower()`; error responses are never cached.
- **`cli.py`** — thin argparse wrapper around `core.lookup()` / `core.format_profile()`. Not wired to `research.py`.

### Env vars

`COMPANYBOOK_API_KEY`, `SITE_ACCESS_TOKEN`, `GEMINI_API_KEY`, `GEMINI_MODEL` (optional), `REPORT_CACHE_TTL_SECONDS` (optional, default 6h), `PORT`. Loaded via `python-dotenv` from `.env` (not committed).

### Deployment

Render, config in `render.yaml` (Build: `pip install -e ".[prod]"`, Start: `gunicorn -w 2 -b 0.0.0.0:$PORT bg_company_lookup.api:app`). Live instance: **https://bg-company-lookup-api.onrender.com** (free plan, no custom domain — uses the Render-provided `.onrender.com` subdomain). Env vars are set directly in the Render dashboard, not read from `.env`.
