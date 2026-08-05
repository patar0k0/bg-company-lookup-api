# Gemini research + cross-check report routes — design

Date: 2026-08-05
Status: Approved

## Context

The project (`src/bg_company_lookup/`) already exposes `GET /api/company?q=...&token=...`,
a Flask wrapper around `core.lookup()` (companybook.bg official registry data). Auth model:
`token` query param checked against `SITE_ACCESS_TOKEN`; 401 on bad/missing token, 400 on
missing/invalid `q`, typed exceptions mapped to specific HTTP codes, no silent failures.

This adds two new routes on top of the Gemini API (`google-genai` SDK) with built-in Google
Search grounding (free tier, no card required, 5000 grounded requests/month as of 2026 on the
Gemini 3.x Flash/Flash-Lite family):

1. `GET /api/research?q=<topic>&token=...` — free-text web research summary via Gemini +
   Google Search grounding.
2. `GET /api/report?q=<name-or-EIK>&token=...` — combines official registry data
   (`core.lookup()`) with the web research above, and asks Gemini to cross-check them,
   explicitly flagging web claims not confirmed by the official registry.

## Non-goals

- Not touching `/api/company` or `core.py`'s existing behavior.
- Not adding a separate auth token for the AI-cost-incurring routes — same `SITE_ACCESS_TOKEN`
  query-param model as `/api/company`, per explicit instruction.
- Not building a UI/CLI for these — API routes only, matching the existing surface.

## Architecture

### New module: `src/bg_company_lookup/research.py`

Mirrors `core.py`'s style: module-level functions + typed exceptions, no classes/state.

```python
class ResearchServiceError(Exception):
    """Gemini API недостъпен/грешка (аналог на LookupServiceError)."""

DEFAULT_MODEL = "gemini-flash-lite-latest"

def research(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    """
    {"query": ..., "answer": ..., "sources": [{"title": ..., "url": ...}, ...]}

    api_key: from GEMINI_API_KEY env if not passed.
    model: from GEMINI_MODEL env if not passed, else DEFAULT_MODEL.

    Raises:
        RuntimeError         — missing GEMINI_API_KEY (mirrors core.lookup's pattern)
        ResearchServiceError — Gemini API call failed (network/SDK error, bad response)
    """

def cross_check(query: str, official_data: dict | None, web_answer: str,
                 api_key: str | None = None, model: str | None = None) -> str:
    """
    Sends the exact cross-check prompt (official registry JSON + web research answer) to
    Gemini (plain generate_content call, no grounding tool needed — comparison only) and
    returns the unified Bulgarian-language report text.

    Raises the same RuntimeError / ResearchServiceError as research().
    """
```

- Client: `google.genai.Client()`, reads `GEMINI_API_KEY` itself when passed via `api_key=`
  (constructed as `genai.Client(api_key=api_key)`).
- Grounding tool: `types.Tool(google_search=types.GoogleSearch())` attached only in `research()`
  (the raw web-search step) — not in `cross_check()`, which only reasons over text already
  gathered.
- Prompt for `research()`: summarize search results about the topic, in Bulgarian, structured,
  with cited sources at the end.
- Prompt for `cross_check()`: the exact Bulgarian prompt template specified by the user,
  filled with `company_json` (official data, or a "not found in registry" note) and
  `research_answer`.
- Sources extracted from `response.candidates[0].grounding_metadata.grounding_chunks`
  (`.web.title`, `.web.uri`), defensively handling `None`/missing chunks (empty list, not
  a crash) since grounding metadata shape is best-effort from the SDK.

### `api.py` changes

Add a small internal helper to avoid repeating the token/`q`/length validation block a 3rd and
4th time:

```python
def _validate_request(app) -> tuple[str, tuple] | None:
    """Returns (q, None) on success, or (None, (json_response, status)) to return early."""
```

(Exact shape decided during implementation — behavior must stay identical to the existing
`/api/company` inline checks: same error messages/status codes.)

**`GET /api/research`**
1. Validate token/`q` (shared helper).
2. Call `research.research(q)`.
3. Map exceptions: `RuntimeError` (no API key) → 500; `ResearchServiceError` → 502 (logged via
   `app.logger.error`, matching `LookupServiceError` handling); unexpected `Exception` → 502
   with logged stack trace (matches `/api/company`'s catch-all).
4. Success → `200 {"query": q, "answer": ..., "sources": [...]}`.

**`GET /api/report`**
1. Validate token/`q` (shared helper).
2. Call `core.lookup(q)`:
   - `CompanyNotFound` → caught, continue with `official_data = None` and a note that the
     company was not found in the official registry (does NOT abort the request).
   - `RuntimeError` (no `COMPANYBOOK_API_KEY`) or `LookupServiceError` (companybook.bg down) →
     these are real failures of the lookup step itself, not "not found" — fail closed, same
     500/502 mapping as `/api/company`.
3. Call `research.research(q)` for web context. Any failure here (missing `GEMINI_API_KEY` →
   500, `ResearchServiceError` → 502) fails the whole request closed — no silent partial
   report, per explicit "no silent failures" requirement. (User confirmed this over graceful
   degradation.)
4. Call `research.cross_check(q, official_data, research_result["answer"])`. Same fail-closed
   mapping.
5. Success → `200 {"query": q, "report": ..., "official_data": official_data,
   "web_context_sources": research_result["sources"]}`.

Only step 2's `CompanyNotFound` degrades gracefully; steps 2's other exceptions, 3, and 4 all
fail closed.

## Config

- `GEMINI_API_KEY` (required for the two new routes; free key from Google AI Studio, no card).
- `GEMINI_MODEL` (optional, default `gemini-flash-lite-latest`, shared by both `research()` and
  `cross_check()` per user's choice of one shared env var over two).
- `pyproject.toml`: add `google-genai>=1.0` to the main `dependencies` list (used directly at
  request time in `api.py`, not optional).
- `.env.example`: add `GEMINI_API_KEY=` and `GEMINI_MODEL=`.
- `render.yaml`: add `GEMINI_API_KEY` (`sync: false`, like the two existing secrets); no need to
  add `GEMINI_MODEL` since it has a code default.
- `README.md`: new section documenting both routes, both env vars, and a one-line pointer to
  Google AI Studio for a free key.

## Testing

- `tests/test_research.py` (new): unit tests for `research()` and `cross_check()`, mocking
  `google.genai.Client` (patch the class where imported in `research.py`, matching the
  project's `@patch("bg_company_lookup.api.lookup")` style). Cases: successful call with
  grounding sources parsed correctly, missing API key → `RuntimeError`, SDK/network exception →
  `ResearchServiceError`.
- `tests/test_api.py` (extended): for each of `/api/research` and `/api/report` — success
  (mocked `research`/`lookup`/`cross_check`), missing token (401), missing `q` (400), upstream
  error (502). Plus one `/api/report`-specific case: `CompanyNotFound` from `lookup` still
  yields 200 with `official_data: null` and a report that was generated (mocked) using the
  research-only context.

## Out of scope / explicitly not doing

- No retry/backoff logic around Gemini calls — matches existing `core.py` behavior (single
  attempt, typed error on failure).
- No caching of research/report results.
- No rate limiting beyond what `SITE_ACCESS_TOKEN` already provides (Gemini's own free-tier
  quota is the backstop, same philosophy as companybook.bg's daily limits today).
