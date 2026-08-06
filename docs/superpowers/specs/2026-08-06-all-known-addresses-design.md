# All known addresses (registry + web) — design

Date: 2026-08-06
Status: Approved

## Context

`core.lookup()` already pulls two addresses from companybook.bg (`company.seat` →
`profile["address"]`, `company.correspondenceSeat` → `profile["correspondence_address"]`), but
the `/api/report` UI never surfaces either — `renderOfficialData()` in `api.py`'s `INDEX_HTML`
only shows name/EIK/status/managers. Separately, a real company can have an actual operating
address (office, shop, warehouse) that differs from its registered seat address and isn't in
companybook.bg at all — only findable via a general web search.

The user wants `/api/report` to surface **all addresses that can be found** for a company: the
ones already in the registry data, plus any additional addresses discoverable via Gemini's
Google Search grounding (same mechanism `research.research()` already uses), with web-found
addresses flagged when they differ from the registered one.

## Non-goals

- Not changing `/api/company` or `core.lookup()`'s existing return shape.
- Not adding a separate on-demand endpoint/button — addresses are gathered automatically as
  part of every `/api/report` call, same as `research()` and `cross_check()` today.
- Not attempting authoritative geocoding/address validation — this is best-effort web search,
  same reliability tier as the rest of `research.py`.

## Architecture

### `research.py` additions

```python
def find_addresses(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    """
    Уеб търсене (Google Search grounding) за всички известни физически адреси на фирмата.

    Връща: {"query": ..., "addresses": [{"address": str, "context": str | None,
                                          "source_url": str | None}, ...]}

    При невалиден/непарсируем JSON отговор от модела: връща addresses=[] (soft degrade),
    не хвърля изключение — само upstream грешки (липсващ ключ, недостъпен Gemini) се
    третират като грешки.

    Хвърля:
        RuntimeError         — липсва GEMINI_API_KEY
        ResearchServiceError — Gemini API недостъпен/грешка при извикване
    """
```

- Uses the same `_client()` / `_generate_with_fallback()` / `google_search` grounding tool as
  `research()`.
- Prompt (Bulgarian, fixed template): asks for all known physical addresses (offices, obekti,
  shops, warehouses) of the named company, from its website, Google Maps, listings, etc.,
  returned as **raw JSON only** — a list of `{"address": ..., "context": ..., "source_url": ...}`
  objects, no markdown fencing or prose.
- Response parsing: strip whitespace/markdown code fences defensively, `json.loads()`; on
  `json.JSONDecodeError` or wrong top-level type, log nothing (matches existing module's lack of
  logging) and return `{"query": query, "addresses": []}` instead of raising — a malformed model
  response is not the same class of failure as an unreachable API.
- `_extract_sources()` is not reused here — sources come from the parsed JSON's `source_url`
  fields, not grounding metadata (the model is asked to cite inline per address).

```python
def merge_addresses(official_data: dict | None, web_result: dict) -> list[dict]:
    """
    Обединява регистровите адреси (от official_data) с намерените в уеб адреси
    (от find_addresses()) в един списък, всеки маркиран със source и (за уеб адресите)
    дали се различава от регистровите.

    Връща списък от:
      {"address": str, "source": "registry" | "web", "label": str,
       "context": str | None, "source_url": str | None, "differs_from_registry": bool | None}

    label за registry: "Адрес на управление" / "Адрес за кореспонденция".
    differs_from_registry е None за registry записи (не е приложимо), bool за web записите.
    """
```

- Pure function, no I/O — easy to unit test in isolation from both `find_addresses()` and
  `core.lookup()`.
- Registry entries: included only if the corresponding field is non-empty; skips
  `correspondence_address` if it's identical (after normalization) to `address`, to avoid
  showing the same address twice.
- Normalization for comparison: lowercase, strip, collapse whitespace, drop `.`/`,` punctuation.
  A web address is flagged `differs_from_registry: True` only if it does not normalize-contain
  and is not normalize-contained-by any registry address string (loose substring match, since
  registry addresses are structured/joined-by-comma and web addresses are free text). If there
  are no registry addresses at all, every web address gets `differs_from_registry: True`.

### `api.py` changes — `/api/report`

Extend the existing `ThreadPoolExecutor(max_workers=2)` to `max_workers=3`, adding a third
concurrent submit for `research.find_addresses(q)` alongside the existing `lookup(q)` and
`research.research(q)` — it needs only the query string, not `official_data`, so it doesn't have
to wait on the lookup step. This keeps latency flat instead of adding a sequential third
round-trip.

Error handling for the new step mirrors the existing `research()` step exactly (fail-closed,
consistent with `/api/report`'s existing rule that every failure in the chain besides
`CompanyNotFound` fails closed — no silent partial reports):
- `RuntimeError` (missing `GEMINI_API_KEY`) → `early_response = (jsonify({"error": ...}), 500)`
- `ResearchServiceError` → logged via `app.logger.error`, `early_response = (..., 502)`
- unexpected `Exception` → logged via `app.logger.exception`, `early_response = (..., 502)`
- `early_response` is only set if not already set by an earlier step (same `early_response or
  (...)` pattern already used for the `research()` step).

After all three futures resolve and no `early_response` was set:
```python
addresses = research.merge_addresses(official_data, addresses_result)
```
added to the final result dict as `"addresses": addresses`, cached in `report_cache` along with
the rest (no separate cache entry/TTL).

Final `/api/report` response shape:
```json
{
  "query": "...",
  "report": "...",
  "official_data": {...} | null,
  "web_context_sources": [...],
  "addresses": [
    {"address": "...", "source": "registry", "label": "Адрес на управление",
     "context": null, "source_url": null, "differs_from_registry": null},
    {"address": "...", "source": "web", "label": null,
     "context": "...", "source_url": "...", "differs_from_registry": true}
  ]
}
```

### UI (`INDEX_HTML` in `api.py`)

New `renderAddresses(addresses)` JS function + a new `<div class="card section">` between the
"Официални данни" and "Обединен доклад" cards. Each address renders as a row with:
- a badge: "регистър" (neutral) or "уеб" (secondary color)
- for web addresses with `differs_from_registry: true`: an additional warning-styled badge
  "различен от регистъра" (reuses `.badge` styling with the existing `--color-destructive` as
  accent, new `.badge.warn` CSS class)
- the address text, and if present, `context` (smaller, muted) and `source_url` as a link
  (reusing the existing `ul.sources`-style link treatment)
- empty state: "Няма намерени адреси." (reuses `.empty` class) if the list is empty

## Testing

- `tests/test_research.py`:
  - `find_addresses()`: successful call parses a valid JSON array from `response.text`
    (mocked `genai.Client`); malformed JSON → `addresses: []`, no exception; missing API key →
    `RuntimeError`; SDK error → `ResearchServiceError` (mirrors existing `research()` tests).
  - `merge_addresses()`: registry-only (no web results), web-only (no `official_data`),
    matching address (no `differs_from_registry` flag), differing address (flag set),
    duplicate `correspondence_address` == `address` (not double-listed).
- `tests/test_api.py`: extend `/api/report` tests to assert the new `addresses` field is present
  on success (mocked `find_addresses`), and that a `find_addresses` failure
  (`ResearchServiceError`) fails the whole request closed (502), matching the existing pattern
  for the `research()` step failing closed.

## Out of scope / explicitly not doing

- No geocoding, address deduplication beyond simple string normalization, or map rendering.
- No retry/backoff around the new Gemini call — same single-attempt-then-typed-error philosophy
  as the rest of `research.py`.
- No change to `/api/company` or `core.py`.
- No separate rate limit/cost control for the third Gemini call beyond what already exists
  (`SITE_ACCESS_TOKEN` gate + Gemini's own free-tier quota + the existing report cache, which
  now also avoids re-triggering `find_addresses` on a cache hit).
