# "Оценка" tab — priority-criteria assessment — design

Date: 2026-08-06
Status: Approved

## Context

The `/` page (`INDEX_HTML` in `src/bg_company_lookup/api.py`) currently renders the
`/api/report` response as three stacked `.card.section` blocks: official registry data,
the unified cross-check report, and web sources.

The user needs a fourth section that checks whether a looked-up company matches the priority
criteria of a specific grant/funding scheme:

1. **Municipality** — project implemented in one of a fixed list of 44 municipalities.
2. **Economic activity** — company's declared NACE/КИД activity falls in one of a fixed list of
   priority sectors (pharma, computer/electronics, chemicals, electrical equipment, machinery,
   vehicles, aviation/defense repair, media/broadcast, telecom, IT, R&D, engineering, etc.).
3. **Registered seat** — company's seat (`седалище`) as of 2025-12-31 is in one of a fixed list
   of 17 oblasti, **and** the investment is realized on the territory of those oblasti.

## Non-goals

- Not building a general-purpose company rating/valuation feature — this is specifically the
  3-criteria priority checklist described above.
- Not verifying "investment realized in these oblasti" automatically — the official registry has
  no data about a specific project's investment location. Always shown as a manual-check note.
- Not tracking historical seat address precisely as of 2025-12-31 — current registry address is
  used as a proxy (see Decisions below).
- Not adding a new HTTP route — the assessment is computed inline as part of `/api/report`.

## Decisions (from brainstorming)

- **Automatic matching where possible.** Criteria 1 and 2 are fully automatic from registry
  data. Criterion 3 is automatic for the "seat in oblast" part; the "investment realized there"
  part is always flagged as requiring manual confirmation.
- **Economic activity matching**: the free-text priority sector list is mapped to real КИД-2008
  (NACE Rev.2 Bulgaria) divisions (2-digit numeric codes). The company's NKID code's first two
  digits are compared against this set of division numbers. Example: "производство на
  лекарствени вещества и продукти" → division `21`.
- **Seat-date precision**: current `address.district` from the registry is used as-is (no
  cross-referencing of `history` for post-2025-12-31 seat changes). Simpler and accurate enough
  for a personal tool.
- **UI**: convert the existing stacked cards into real tabs (single visible panel, tab nav
  above), rather than appending a 4th card. Applies to all 4 sections, not just the new one.

## Architecture

### New module: `src/bg_company_lookup/priority.py`

Pure functions, no I/O, no external calls — mirrors the project's preference for
independently-testable units.

```python
PRIORITY_MUNICIPALITIES: frozenset[str]  # the 44 municipality names, verbatim from the user

PRIORITY_NACE_DIVISIONS: dict[str, str]  # "21" -> "Производство на лекарствени вещества и продукти", etc.
                                          # covers divisions: 20, 21, 26, 27, 28, 29, 30, 32, 33,
                                          # 59, 60, 61, 62, 63, 71, 72

PRIORITY_DISTRICTS: frozenset[str]  # the 17 oblast names, verbatim from the user


def evaluate(company_data: dict) -> dict:
    """
    Pure function — no network calls. Takes core.lookup()'s output shape and returns:

    {
      "municipality": {"matched": bool, "value": str | None},
      "activity": {
        "matched": bool,
        "matched_divisions": [{"code": "21", "description": "..."}],  # empty if no match
        "company_nkids": [{"code": "4525", "description": "..."}],
      },
      "district": {
        "matched": bool,
        "value": str | None,
        "investment_location_note": "Реализацията на инвестицията в тази област изисква ръчна проверка.",
      },
      "auto_matched_count": int,  # 0-2 (only municipality + activity are fully automatic)
      "total_criteria": 3,
    }
    """
```

Matching rules:
- **Municipality**: normalized (strip, casefold) exact match of `company_data["address"]["municipality"]`
  against `PRIORITY_MUNICIPALITIES`.
- **Activity**: for each entry in `company_data["activity"]["nkids"]`, take `code[:2]`, look up in
  `PRIORITY_NACE_DIVISIONS`. Matched if any NKID code's division is in the priority set.
- **District**: normalized exact match of `company_data["address"]["district"]` against
  `PRIORITY_DISTRICTS`. `investment_location_note` is always present (not conditional on match)
  since it can never be auto-verified.

### `api.py` changes

In `/api/report`, after a successful `lookup()` (i.e. `official_data is not None`):

```python
priority_assessment = priority.evaluate(official_data) if official_data else None
```

Added to the JSON response as a new top-level key:

```json
{
  "query": "...",
  "report": "...",
  "official_data": {...},
  "web_context_sources": [...],
  "priority_assessment": {...} | null
}
```

`null` when the company wasn't found in the registry (frontend shows an explanatory message
instead of the checklist). No new exception handling needed — `priority.evaluate()` cannot fail
(pure dict lookups over already-validated data).

### Frontend (`INDEX_HTML`)

**Tab conversion**: replace the three stacked `<div class="card section">` blocks with:
- A tab-nav bar (4 buttons: "Официални данни", "Обединен доклад", "Уеб източници", "Оценка").
- 4 panels, one visible at a time via a `.active` class toggled by a small JS click handler.
- Existing card styling (background/border/radius/padding) moves from `.card` wrapping each
  section to wrapping the whole tab panel area, so the visual look stays close to today's.

**New "Оценка" panel**, rendered from `body.priority_assessment`:
- Summary line at top: `"{auto_matched_count} от 2 автоматично проверими критерия отговарят"`.
- Three rows, each with a ✅/❌ icon + label:
  1. Община — matched municipality name, or "не съвпада с приоритетен списък".
  2. Икономическа дейност — matched division description(s), or "не съвпада"; always shows the
     company's own NKID code + description for context.
  3. Област на седалище — matched/not, **plus** a permanently-shown ⚠️ note that investment
     location must be checked manually (this row is never a clean ✅, always paired with the
     caveat).
- If `priority_assessment` is `null`: "Фирмата не е намерена в официалния регистър — оценката по
  приоритетни критерии не може да се направи."

## Testing

- `tests/test_priority.py` (new): unit tests for `evaluate()` against fixture `company_data`
  dicts — municipality match/no-match, activity match via NKID division, no NKID data, district
  match/no-match, multiple NKID codes where only one matches. No mocking needed (pure function).
- `tests/test_api.py` (extended): `/api/report` response includes `priority_assessment` matching
  a mocked `lookup()` fixture; `priority_assessment` is `null` when `lookup()` raises
  `CompanyNotFound`.

## Out of scope / explicitly not doing

- No configuration UI for editing the priority lists — they're hardcoded constants matching the
  exact criteria given by the user for this specific scheme.
- No historical seat-address lookback via `history` — current address only (see Decisions).
- No automatic verification of investment location — always a manual-check note.
