# "Оценка" tab (priority-criteria assessment) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4th "Оценка" tab to the `/` report page that checks a looked-up company against 3 hardcoded priority criteria (municipality, economic activity, seat oblast) of a grant scheme, and convert the existing stacked result cards into real tabs.

**Architecture:** New pure-function module `priority.py` (no I/O) computes the match; `/api/report` calls it inline and adds a `priority_assessment` key to its JSON response; the embedded frontend (`INDEX_HTML` in `api.py`) gets a small tab-nav + 4th panel, driven by one delegated click listener.

**Tech Stack:** Python 3.12, Flask, pytest, vanilla JS (no framework — matches existing `INDEX_HTML`).

Design doc: `docs/superpowers/specs/2026-08-06-priority-assessment-tab-design.md`

---

### Task 1: `priority.py` — pure matching module

**Files:**
- Create: `src/bg_company_lookup/priority.py`
- Test: `tests/test_priority.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_priority.py`:

```python
from bg_company_lookup.priority import evaluate


def _company(municipality=None, district=None, nkids=None):
    return {
        "address": {"municipality": municipality, "district": district},
        "activity": {"subject": "...", "nkids": nkids or []},
    }


def test_municipality_match():
    company = _company(municipality="Враца")
    result = evaluate(company)
    assert result["municipality"]["matched"] is True
    assert result["municipality"]["value"] == "Враца"


def test_municipality_no_match():
    company = _company(municipality="София")
    result = evaluate(company)
    assert result["municipality"]["matched"] is False


def test_municipality_match_is_case_and_whitespace_insensitive():
    company = _company(municipality="  враца  ")
    result = evaluate(company)
    assert result["municipality"]["matched"] is True


def test_activity_matches_priority_nace_division():
    company = _company(nkids=[{"code": "2110", "description": "Производство на лекарства"}])
    result = evaluate(company)
    assert result["activity"]["matched"] is True
    assert result["activity"]["matched_divisions"] == [
        {"code": "21", "description": "Производство на лекарствени вещества и продукти"}
    ]
    assert result["activity"]["company_nkids"] == [
        {"code": "2110", "description": "Производство на лекарства"}
    ]


def test_activity_no_match():
    company = _company(nkids=[{"code": "4525", "description": "Строителни дейности"}])
    result = evaluate(company)
    assert result["activity"]["matched"] is False
    assert result["activity"]["matched_divisions"] == []


def test_activity_matches_when_any_of_multiple_nkids_matches():
    company = _company(
        nkids=[
            {"code": "4525", "description": "Строителни дейности"},
            {"code": "6201", "description": "Компютърно програмиране"},
        ]
    )
    result = evaluate(company)
    assert result["activity"]["matched"] is True
    assert result["activity"]["matched_divisions"] == [
        {"code": "62", "description": "Дейности в областта на информационните технологии"}
    ]


def test_district_match():
    company = _company(district="Хасково")
    result = evaluate(company)
    assert result["district"]["matched"] is True
    assert "изисква ръчна проверка" in result["district"]["investment_location_note"]


def test_district_no_match():
    company = _company(district="Варна")
    result = evaluate(company)
    assert result["district"]["matched"] is False
    assert "изисква ръчна проверка" in result["district"]["investment_location_note"]


def test_auto_matched_count_counts_municipality_and_activity_only():
    company = _company(
        municipality="Враца",
        district="Варна",
        nkids=[{"code": "2110", "description": "..."}],
    )
    result = evaluate(company)
    assert result["auto_matched_count"] == 2
    assert result["total_criteria"] == 3


def test_evaluate_handles_missing_address_and_activity():
    result = evaluate({})
    assert result["municipality"]["matched"] is False
    assert result["activity"]["matched"] is False
    assert result["district"]["matched"] is False
    assert result["auto_matched_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_priority.py -v`
Expected: `ModuleNotFoundError: No module named 'bg_company_lookup.priority'` (or collection error) — the module doesn't exist yet.

- [ ] **Step 3: Write `priority.py`**

Create `src/bg_company_lookup/priority.py`:

```python
"""
Проверка на фирмени данни (изхода на core.lookup()) срещу приоритетните критерии
на конкретна грантова схема: община на изпълнение, икономическа дейност (КИД-2008)
и област на седалище. Чисти функции, без мрежови извиквания.
"""

from __future__ import annotations

PRIORITY_MUNICIPALITIES: frozenset[str] = frozenset(
    {
        "Враца", "Ловеч", "Лом", "Видин", "Монтана", "Силистра", "Горна Оряховица",
        "Севлиево", "Габрово", "Свищов", "Търговище", "Добрич", "Шумен", "Аксаково",
        "Кюстендил", "Петрич", "Сандански", "Перник", "Дупница", "Гоце Делчев",
        "Гърмен", "Сатовча", "Самоков", "Ботевград", "Благоевград", "Сливен",
        "Казанлък", "Карнобат", "Ямбол", "Велинград", "Смолян", "Пазарджик",
        "Карлово", "Хасково", "Пловдив", "Свиленград", "Панагюрище", "Пещера",
        "Кърджали", "Ардино", "Джебел", "Черноочене", "Димитровград",
    }
)

PRIORITY_DISTRICTS: frozenset[str] = frozenset(
    {
        "Хасково", "Силистра", "Сливен", "Кюстендил", "Видин", "Монтана", "Кърджали",
        "Перник", "Пазарджик", "Благоевград", "Смолян", "Добрич", "Разград", "Шумен",
        "Плевен", "Ямбол", "Ловеч",
    }
)

# Приоритетни КИД-2008 (NACE Rev.2 BG) раздели — 2-цифрен код -> описание.
# Мапнати от свободния текст на критериите към реални класове на разделите.
PRIORITY_NACE_DIVISIONS: dict[str, str] = {
    "20": "Производство на химични продукти",
    "21": "Производство на лекарствени вещества и продукти",
    "26": "Производство на компютърна и комуникационна техника, електронни и оптични продукти",
    "27": "Производство на електрически съоръжения",
    "28": "Производство на машини и оборудване, с общо и специално предназначение",
    "29": "Производство на автомобили, ремаркета и полуремаркета",
    "30": "Производство на превозни средства, без автомобили",
    "32": "Други разнообразни производства, некласифицирани другаде",
    "33": (
        "Ремонт и поддържане на бойни бронирани транспортни машини, военни "
        "плавателни съдове, въздухоплавателни и космически средства"
    ),
    "59": "Производство на филми и телевизионни предавания, звукозаписване и издаване на музика",
    "60": "Радио- и телевизионна дейност, информационни агенции и разпространение на друго съдържание",
    "61": "Телекомуникации",
    "62": "Дейности в областта на информационните технологии",
    "63": "Инфраструктура за информационни технологии, обработка на данни, хостинг и други информационни услуги",
    "71": "Архитектурни и инженерни дейности; технически изпитвания и анализи",
    "72": "Научноизследователска и развойна дейност",
}

INVESTMENT_LOCATION_NOTE = (
    "Реализацията на инвестицията в тази област изисква ръчна проверка — "
    "официалният регистър не съдържа информация за мястото на изпълнение на проекта."
)


def _normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def evaluate(company_data: dict) -> dict:
    """
    Чиста функция — без мрежови извиквания. Приема речник във формата на
    core.lookup()'s изход и връща оценка по 3-те приоритетни критерия.
    """
    address = company_data.get("address") or {}
    activity = company_data.get("activity") or {}
    nkids = activity.get("nkids") or []

    municipality_value = address.get("municipality")
    municipality_matched = _normalize(municipality_value) in {
        _normalize(m) for m in PRIORITY_MUNICIPALITIES
    }

    company_nkids = [{"code": n.get("code"), "description": n.get("description")} for n in nkids]

    matched_divisions = []
    seen_divisions = set()
    for n in nkids:
        division = (n.get("code") or "")[:2]
        if division in PRIORITY_NACE_DIVISIONS and division not in seen_divisions:
            seen_divisions.add(division)
            matched_divisions.append(
                {"code": division, "description": PRIORITY_NACE_DIVISIONS[division]}
            )

    district_value = address.get("district")
    district_matched = _normalize(district_value) in {_normalize(d) for d in PRIORITY_DISTRICTS}

    auto_matched_count = int(municipality_matched) + int(bool(matched_divisions))

    return {
        "municipality": {
            "matched": municipality_matched,
            "value": municipality_value,
        },
        "activity": {
            "matched": bool(matched_divisions),
            "matched_divisions": matched_divisions,
            "company_nkids": company_nkids,
        },
        "district": {
            "matched": district_matched,
            "value": district_value,
            "investment_location_note": INVESTMENT_LOCATION_NOTE,
        },
        "auto_matched_count": auto_matched_count,
        "total_criteria": 3,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_priority.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Lint**

Run: `ruff check src/bg_company_lookup/priority.py tests/test_priority.py && ruff format --check src/bg_company_lookup/priority.py tests/test_priority.py`
Expected: no errors. If formatting differs, run `ruff format src/bg_company_lookup/priority.py tests/test_priority.py` and re-check.

- [ ] **Step 6: Commit**

```bash
git add src/bg_company_lookup/priority.py tests/test_priority.py
git commit -m "Добавя priority.py — сверка на фирма срещу приоритетни критерии"
```

---

### Task 2: Wire `priority.evaluate()` into `/api/report`

**Files:**
- Modify: `src/bg_company_lookup/api.py:22` (import), `src/bg_company_lookup/api.py:514-535` (`api_report`)
- Test: `tests/test_api.py:160-202`

- [ ] **Step 1: Write/extend the failing tests**

In `tests/test_api.py`, replace the `test_report_returns_combined_json` test (currently lines 160-180) with a version whose mocked company data includes `address`/`activity`, and add assertions on `priority_assessment`:

```python
@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_combined_json(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {
        "uic": "106590295",
        "name": "ДЕКОРАМЕТ",
        "address": {"municipality": "Враца", "district": "Враца"},
        "activity": {"nkids": [{"code": "2110", "description": "Производство на лекарства"}]},
    }
    mock_research_module.research.return_value = {
        "query": "106590295",
        "answer": "уеб контекст",
        "sources": [{"title": "т", "url": "u"}],
    }
    mock_research_module.cross_check.return_value = "обединен доклад"

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["report"] == "обединен доклад"
    assert body["official_data"]["uic"] == "106590295"
    assert body["web_context_sources"] == [{"title": "т", "url": "u"}]
    assert body["priority_assessment"]["municipality"]["matched"] is True
    assert body["priority_assessment"]["activity"]["matched"] is True
    assert body["priority_assessment"]["auto_matched_count"] == 2
    mock_research_module.cross_check.assert_called_once_with(
        "106590295", mock_lookup.return_value, "уеб контекст"
    )
```

Also extend `test_report_degrades_when_company_not_found` (currently lines 183-202) with one more assertion — add this line right after `assert body["official_data"] is None`:

```python
    assert body["priority_assessment"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k report`
Expected: `test_report_returns_combined_json` and `test_report_degrades_when_company_not_found` FAIL with `KeyError: 'priority_assessment'`.

- [ ] **Step 3: Wire it up in `api.py`**

Add the import near the other local imports (`src/bg_company_lookup/api.py:22`, right after `from bg_company_lookup import research`):

```python
from bg_company_lookup import priority, research
```

(This replaces the existing single-name import line `from bg_company_lookup import research`.)

In `api_report()`, right after the `if early_response: return early_response` check (`src/bg_company_lookup/api.py:514-515`), add:

```python
        if early_response:
            return early_response

        priority_assessment = priority.evaluate(official_data) if official_data else None

        try:
```

(The `try:` here is the existing `cross_check` call block — only the new `priority_assessment` line is inserted before it.)

Then add `priority_assessment` to the `result` dict (`src/bg_company_lookup/api.py:528-533`):

```python
        result = {
            "query": q,
            "report": report_text,
            "official_data": official_data,
            "web_context_sources": research_result["sources"],
            "priority_assessment": priority_assessment,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k report`
Expected: all report tests PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS (no regressions elsewhere).

- [ ] **Step 6: Lint**

Run: `ruff check src/bg_company_lookup/api.py tests/test_api.py && ruff format --check src/bg_company_lookup/api.py tests/test_api.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/bg_company_lookup/api.py tests/test_api.py
git commit -m "Добавя priority_assessment в отговора на /api/report"
```

---

### Task 3: Frontend — real tabs + "Оценка" panel

**Files:**
- Modify: `src/bg_company_lookup/api.py` (the `INDEX_HTML` string, CSS block ~line 249, JS block ~lines 296-388)
- Test: `tests/test_api.py:30-37` (`test_index_returns_html_page`)

- [ ] **Step 1: Write/extend the failing test**

Replace `test_index_returns_html_page` in `tests/test_api.py` (currently lines 30-37) with:

```python
def test_index_returns_html_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert b"<form" in resp.data
    assert b"/api/report" in resp.data
    assert b'<label for="q">' in resp.data
    assert b'<label for="token">' in resp.data
    assert b"marked@" in resp.data
    assert b"dompurify@" in resp.data
    assert b'data-tab="priority"' in resp.data
    assert b"tab-btn" in resp.data
    assert "Оценка".encode() in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v -k test_index_returns_html_page`
Expected: FAIL — no `data-tab="priority"` in the current HTML.

- [ ] **Step 3: Add tab CSS**

In `src/bg_company_lookup/api.py`, right after the `.empty { ... }` rule (currently `src/bg_company_lookup/api.py:249`) and before the `@media (prefers-reduced-motion: reduce)` block, insert:

```css
  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 1rem;
  }

  .tab-btn {
    font-family: var(--font-heading);
    font-weight: 600;
    font-size: 0.85rem;
    padding: 0.5rem 0.9rem;
    border: 1px solid var(--color-border);
    border-radius: 8px;
    background: var(--color-surface);
    color: var(--color-muted-fg);
    cursor: pointer;
  }

  .tab-btn.active { background: var(--color-primary); color: #fff; border-color: var(--color-primary); }
  .tab-btn:focus-visible { outline: 2px solid var(--color-ring); outline-offset: 2px; }

  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  .priority-list {
    list-style: none; padding: 0; margin: 0.75rem 0 0;
    display: flex; flex-direction: column; gap: 0.75rem;
  }
  .priority-list li {
    border: 1px solid var(--color-border); border-radius: 8px;
    padding: 0.6rem 0.75rem; font-size: 0.9rem;
  }
  .priority-list .hint { display: block; margin-top: 0.3rem; }
```

- [ ] **Step 4: Replace the stacked-cards result template with tabs**

In `src/bg_company_lookup/api.py`, replace the `resultEl.innerHTML` block inside the form submit handler (currently lines 366-380):

Old:
```javascript
    statusEl.innerHTML = '';
    resultEl.innerHTML = `
      <div class="card section">
        <h2>Официални данни от регистъра</h2>
        ${renderOfficialData(body.official_data)}
      </div>
      <div class="card section">
        <h2>Обединен доклад</h2>
        <div class="report-text">${renderMarkdown(body.report)}</div>
      </div>
      <div class="card section">
        <h2>Уеб източници</h2>
        ${renderSources(body.web_context_sources)}
      </div>
    `;
```

New:
```javascript
    statusEl.innerHTML = '';
    resultEl.innerHTML = `
      <div class="tabs" role="tablist">
        <button type="button" class="tab-btn active" data-tab="official" role="tab" aria-selected="true">Официални данни</button>
        <button type="button" class="tab-btn" data-tab="report" role="tab" aria-selected="false">Обединен доклад</button>
        <button type="button" class="tab-btn" data-tab="sources" role="tab" aria-selected="false">Уеб източници</button>
        <button type="button" class="tab-btn" data-tab="priority" role="tab" aria-selected="false">Оценка</button>
      </div>
      <div class="card section">
        <div class="tab-panel active" id="tab-official">
          <h2>Официални данни от регистъра</h2>
          ${renderOfficialData(body.official_data)}
        </div>
        <div class="tab-panel" id="tab-report">
          <h2>Обединен доклад</h2>
          <div class="report-text">${renderMarkdown(body.report)}</div>
        </div>
        <div class="tab-panel" id="tab-sources">
          <h2>Уеб източници</h2>
          ${renderSources(body.web_context_sources)}
        </div>
        <div class="tab-panel" id="tab-priority">
          <h2>Оценка по приоритетни критерии</h2>
          ${renderPriorityAssessment(body.priority_assessment)}
        </div>
      </div>
    `;
```

- [ ] **Step 5: Add `renderPriorityAssessment()` and the tab-click listener**

In `src/bg_company_lookup/api.py`, add the new render function right after `renderSources()` (currently ends at line 333, just before the blank line preceding `form.addEventListener`):

```javascript
function renderPriorityAssessment(assessment) {
  if (!assessment) {
    return '<p class="empty">Фирмата не е намерена в официалния регистър — ' +
      'оценката по приоритетни критерии не може да се направи.</p>';
  }
  const icon = (matched) => matched ? '✅' : '❌';
  const m = assessment.municipality;
  const a = assessment.activity;
  const d = assessment.district;

  const municipalityLine = m.matched
    ? 'съвпада с "' + escapeHtml(m.value) + '"'
    : 'не съвпада с приоритетния списък' + (m.value ? ' (' + escapeHtml(m.value) + ')' : '');

  const divisions = (a.matched_divisions || [])
    .map(x => escapeHtml(x.code + ' — ' + x.description)).join('; ');
  const nkids = (a.company_nkids || [])
    .map(x => escapeHtml((x.code || '?') + ' — ' + (x.description || ''))).join(', ') || '—';
  const activityLine = a.matched
    ? 'съвпада с приоритетен клас: ' + divisions
    : 'не съвпада с приоритетния списък';

  const districtLine = d.matched
    ? 'съвпада с "' + escapeHtml(d.value) + '"'
    : 'не съвпада с приоритетния списък' + (d.value ? ' (' + escapeHtml(d.value) + ')' : '');

  return `
    <p>${assessment.auto_matched_count} от 2 автоматично проверими критерия отговарят.</p>
    <ul class="priority-list">
      <li>${icon(m.matched)} <strong>Община:</strong> ${municipalityLine}</li>
      <li>${icon(a.matched)} <strong>Икономическа дейност:</strong> ${activityLine}
        <span class="hint">НКИД на фирмата: ${nkids}</span></li>
      <li>${icon(d.matched)} <strong>Област на седалище:</strong> ${districtLine}
        <span class="hint">⚠️ ${escapeHtml(d.investment_location_note)}</span></li>
    </ul>
  `;
}
```

Then, right after the `const resultEl = document.getElementById('result');` line (currently `src/bg_company_lookup/api.py:295`), add a delegated click listener so tab-switching keeps working across re-renders (the tabs are re-created on every search):

```javascript
resultEl.addEventListener('click', (e) => {
  const btn = e.target.closest('.tab-btn');
  if (!btn) return;
  const tab = btn.dataset.tab;
  resultEl.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b === btn);
    b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
  });
  resultEl.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + tab);
  });
});
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_api.py -v -k test_index_returns_html_page`
Expected: PASS.

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS.

- [ ] **Step 8: Lint**

Run: `ruff check src/bg_company_lookup/api.py && ruff format --check src/bg_company_lookup/api.py`
Expected: no errors.

- [ ] **Step 9: Manual browser check**

Run: `python -m bg_company_lookup.api`, open `http://localhost:5000/`, search a real company (e.g. ЕИК `106581200`), confirm:
- 4 tab buttons appear, clicking switches the visible panel, active tab is visually highlighted.
- "Оценка" tab shows the 3-criteria checklist with icons and the manual-check note under "Област на седалище".
- Searching an unrecognized company name shows the "не е намерена в официалния регистър" message in the "Оценка" tab (and `official_data` empty message in "Официални данни" tab) instead of a crash.

- [ ] **Step 10: Commit**

```bash
git add src/bg_company_lookup/api.py tests/test_api.py
git commit -m "Превръща резултатните секции в табове и добавя таб Оценка"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md:62-64`

- [ ] **Step 1: Update the `/api/report` response shape documentation**

In `README.md`, replace (currently lines 62-64):

```markdown
Извиква вътрешно и `/api/company`-логиката (`core.lookup`), и `/api/research`-логиката,
после праща двата резултата на Gemini да ги сравни — всичко от уеб search, което НЕ се
потвърждава от официалния регистър, се отбелязва изрично като непотвърдено. Връща
`{"query", "report", "official_data", "web_context_sources"}`. Ако фирмата не е намерена
в официалния регистър, `official_data` е `null`, а докладът се генерира само от уеб частта.
```

With:

```markdown
Извиква вътрешно и `/api/company`-логиката (`core.lookup`), и `/api/research`-логиката,
после праща двата резултата на Gemini да ги сравни — всичко от уеб search, което НЕ се
потвърждава от официалния регистър, се отбелязва изрично като непотвърдено. Връща
`{"query", "report", "official_data", "web_context_sources", "priority_assessment"}`. Ако
фирмата не е намерена в официалния регистър, `official_data` и `priority_assessment` са
`null`, а докладът се генерира само от уеб частта.

`priority_assessment` е резултат от чисто локална сверка (без допълнителни заявки) на
фирмата срещу 3 фиксирани приоритетни критерия (община, икономическа дейност по КИД-2008,
област на седалище) на конкретна грантова схема — виж `src/bg_company_lookup/priority.py`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Документира priority_assessment в /api/report"
```

---

## Post-implementation

- Full suite: `pytest -v` and `ruff check . && ruff format --check .` both green.
- Manual browser check from Task 3 Step 9 done.
