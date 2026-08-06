# All Known Addresses (Registry + Web) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/api/report` gathers and returns *all* known addresses for a company — the ones already in the companybook.bg registry data plus any additional physical addresses discoverable via a Gemini web search — clearly labeled by source, with web-found addresses flagged when they differ from the registered one.

**Architecture:** Two new pure/near-pure additions to `research.py` (`find_addresses()` — a third Gemini-grounded call mirroring `research()`'s shape, and `merge_addresses()` — a pure function reconciling registry vs. web addresses). `api.py`'s `/api/report` route adds a third concurrent `ThreadPoolExecutor` task for `find_addresses()` (alongside the existing `lookup()`/`research()` pair) so total latency doesn't grow, then calls `merge_addresses()` after all three resolve. The UI gets a new "Адреси" card between the existing "Официални данни" and "Обединен доклад" cards.

**Tech Stack:** Python 3.10+, Flask, `google-genai` SDK (already a dependency), `pytest` + `unittest.mock`.

**Branch:** `design/all-known-addresses` (already checked out). This branch forked before the tabs/priority-assessment UI rework on `feature/priority-assessment-tab` — `api.py` here still has the original card-based layout. All file/line references below are to this branch's current state.

---

## Task 1: `find_addresses()` in `research.py`

**Files:**
- Modify: `src/bg_company_lookup/research.py`
- Test: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_research.py` (after the existing `research()`/`cross_check()` tests, before the `TestFallback`-style tests at the bottom — i.e. right after `test_cross_check_raises_service_error_on_sdk_failure`, before `test_research_falls_back_to_next_model_on_429`):

```python
def test_find_addresses_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        find_addresses("Декорамет ЕООД", api_key=None)


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_returns_parsed_list(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='[{"address": "гр. София, ул. Тест 1", "context": "офис", '
        '"source_url": "https://example.bg"}]',
        with_sources=False,
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["query"] == "Декорамет ЕООД"
    assert result["addresses"] == [
        {
            "address": "гр. София, ул. Тест 1",
            "context": "офис",
            "source_url": "https://example.bg",
        }
    ]


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_strips_markdown_code_fence(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='```json\n[{"address": "гр. Пловдив, бул. Тест 5"}]\n```',
        with_sources=False,
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == [
        {"address": "гр. Пловдив, бул. Тест 5", "context": None, "source_url": None}
    ]


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_returns_empty_list_on_invalid_json(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text="За съжаление не намерих нищо конкретно.", with_sources=False
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == []


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_returns_empty_list_when_top_level_not_a_list(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='{"address": "гр. София"}', with_sources=False
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == []


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_skips_items_without_address_field(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='[{"context": "няма адрес поле"}, "не е обект", '
        '{"address": "гр. Варна, ул. Валидна 2"}]',
        with_sources=False,
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == [
        {"address": "гр. Варна, ул. Валидна 2", "context": None, "source_url": None}
    ]


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_raises_service_error_on_sdk_failure(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.side_effect = RuntimeError("boom")

    with pytest.raises(ResearchServiceError):
        find_addresses("Декорамет ЕООД", api_key="fake-key")
```

Update the import at the top of `tests/test_research.py`:

```python
from bg_company_lookup.research import ResearchServiceError, cross_check, find_addresses, research
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research.py -v -k find_addresses`
Expected: FAIL with `ImportError: cannot import name 'find_addresses'`

- [ ] **Step 3: Implement `find_addresses()` in `research.py`**

Add `import re` is NOT needed here (that's Task 2) — only `json` is needed and it's already imported at the top of `research.py`.

Add this after `cross_check()` (end of file, after line 163's closing of `cross_check`):

```python
ADDRESSES_PROMPT_TEMPLATE = """Намери всички известни физически адреси на фирмата „{query}“ — \
офиси, обекти, магазини, складове, производствени бази — от сайта на фирмата, Google Maps, \
бизнес указатели, обяви и други източници.

Върни САМО чист JSON списък (без markdown форматиране, без обяснения преди или след), от обекти \
във формат:
[{{"address": "пълен адрес като текст", "context": "кратко описание откъде/какво е (или null)", \
"source_url": "URL на източника (или null)"}}]

Ако не намериш нищо конкретно, върни []."""


def _parse_addresses_json(text: str | None) -> list[dict]:
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    addresses = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get("address"):
            continue
        addresses.append(
            {
                "address": item.get("address"),
                "context": item.get("context"),
                "source_url": item.get("source_url"),
            }
        )
    return addresses


def find_addresses(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    """
    Уеб търсене (Google Search grounding) за всички известни физически адреси на фирмата.

    Връща: {"query": ..., "addresses": [{"address": str, "context": str | None,
                                          "source_url": str | None}, ...]}

    При невалиден/непарсируем JSON отговор от модела връща addresses=[] (soft degrade) —
    само upstream грешки (липсващ ключ, недостъпен Gemini) се третират като изключения.

    Хвърля:
        RuntimeError         — липсва GEMINI_API_KEY
        ResearchServiceError — Gemini API недостъпен/грешка при извикване
    """
    client = _client(api_key)
    prompt = ADDRESSES_PROMPT_TEMPLATE.format(query=query)
    response = _generate_with_fallback(
        client,
        prompt,
        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        model=model,
    )

    return {"query": query, "addresses": _parse_addresses_json(response.text)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research.py -v -k find_addresses`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/bg_company_lookup/research.py tests/test_research.py
git commit -m "$(cat <<'EOF'
Добавя research.find_addresses() — уеб търсене на всички известни адреси

EOF
)"
```

---

## Task 2: `merge_addresses()` in `research.py`

**Files:**
- Modify: `src/bg_company_lookup/research.py`
- Test: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_research.py`, after the `find_addresses` tests from Task 1:

```python
def test_merge_addresses_lists_seat_and_correspondence_when_different():
    official_data = {
        "address": {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"},
        "correspondence_address": {
            "street": "ул. Втора",
            "streetNumber": "2",
            "settlement": "Пловдив",
        },
    }

    result = merge_addresses(official_data, {"addresses": []})

    assert result == [
        {
            "address": "ул. Първа, 1, София",
            "source": "registry",
            "label": "Адрес на управление",
            "context": None,
            "source_url": None,
            "differs_from_registry": None,
        },
        {
            "address": "ул. Втора, 2, Пловдив",
            "source": "registry",
            "label": "Адрес за кореспонденция",
            "context": None,
            "source_url": None,
            "differs_from_registry": None,
        },
    ]


def test_merge_addresses_skips_duplicate_correspondence_address():
    same_address = {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"}
    official_data = {"address": same_address, "correspondence_address": dict(same_address)}

    result = merge_addresses(official_data, {"addresses": []})

    assert len(result) == 1
    assert result[0]["label"] == "Адрес на управление"


def test_merge_addresses_all_web_addresses_differ_when_no_official_data():
    web_result = {"addresses": [{"address": "гр. Варна, ул. Уеб 1", "context": None,
                                  "source_url": None}]}

    result = merge_addresses(None, web_result)

    assert result == [
        {
            "address": "гр. Варна, ул. Уеб 1",
            "source": "web",
            "label": None,
            "context": None,
            "source_url": None,
            "differs_from_registry": True,
        }
    ]


def test_merge_addresses_flags_web_address_matching_registry_as_not_differing():
    official_data = {
        "address": {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"}
    }
    web_result = {"addresses": [{"address": "ул. Първа 1, София, България",
                                  "context": "сайт", "source_url": "https://x.bg"}]}

    result = merge_addresses(official_data, web_result)

    web_entry = next(a for a in result if a["source"] == "web")
    assert web_entry["differs_from_registry"] is False


def test_merge_addresses_flags_web_address_differing_from_registry():
    official_data = {
        "address": {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"}
    }
    web_result = {"addresses": [{"address": "гр. Бургас, ул. Съвсем Друга 9",
                                  "context": "офис", "source_url": "https://x.bg"}]}

    result = merge_addresses(official_data, web_result)

    web_entry = next(a for a in result if a["source"] == "web")
    assert web_entry["differs_from_registry"] is True


def test_merge_addresses_skips_web_items_without_address_text():
    result = merge_addresses(None, {"addresses": [{"address": "", "context": None,
                                                     "source_url": None}]})

    assert result == []
```

Update the import at the top of `tests/test_research.py`:

```python
from bg_company_lookup.research import (
    ResearchServiceError,
    cross_check,
    find_addresses,
    merge_addresses,
    research,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research.py -v -k merge_addresses`
Expected: FAIL with `ImportError: cannot import name 'merge_addresses'`

- [ ] **Step 3: Implement `merge_addresses()` in `research.py`**

Add `import re` to the top-level imports of `research.py` (currently `import json` and `import os` — insert `import re` alphabetically between them):

```python
import json
import os
import re
```

Add this after `find_addresses()` (end of file):

```python
def _normalize_address(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[.,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _registry_address_text(addr: dict | None) -> str | None:
    if not addr:
        return None
    parts = [
        addr.get("street"),
        addr.get("streetNumber"),
        addr.get("settlement"),
        addr.get("municipality"),
        addr.get("district"),
        addr.get("postCode"),
    ]
    text = ", ".join(p for p in parts if p)
    return text or None


def merge_addresses(official_data: dict | None, web_result: dict) -> list[dict]:
    """
    Обединява регистровите адреси (от official_data, резултат на core.lookup()) с намерените
    в уеб адреси (от find_addresses()) в един списък, всеки маркиран със source.

    Връща списък от:
      {"address": str, "source": "registry" | "web", "label": str | None,
       "context": str | None, "source_url": str | None, "differs_from_registry": bool | None}

    label е зададен само за registry записи. differs_from_registry е None за registry записи
    (не е приложимо) и bool за web записите — True, ако адресът не съвпада (дори частично,
    като подниз след нормализация) с нито един регистров адрес.
    """
    merged = []
    registry_texts = []

    if official_data:
        seat_text = _registry_address_text(official_data.get("address"))
        if seat_text:
            merged.append(
                {
                    "address": seat_text,
                    "source": "registry",
                    "label": "Адрес на управление",
                    "context": None,
                    "source_url": None,
                    "differs_from_registry": None,
                }
            )
            registry_texts.append(_normalize_address(seat_text))

        corr_text = _registry_address_text(official_data.get("correspondence_address"))
        if corr_text and _normalize_address(corr_text) not in registry_texts:
            merged.append(
                {
                    "address": corr_text,
                    "source": "registry",
                    "label": "Адрес за кореспонденция",
                    "context": None,
                    "source_url": None,
                    "differs_from_registry": None,
                }
            )
            registry_texts.append(_normalize_address(corr_text))

    for item in (web_result or {}).get("addresses", []):
        web_text = item.get("address")
        if not web_text:
            continue
        normalized_web = _normalize_address(web_text)
        differs = not any(
            normalized_web in reg or reg in normalized_web for reg in registry_texts
        )
        merged.append(
            {
                "address": web_text,
                "source": "web",
                "label": None,
                "context": item.get("context"),
                "source_url": item.get("source_url"),
                "differs_from_registry": differs,
            }
        )

    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research.py -v -k merge_addresses`
Expected: 6 tests PASS

- [ ] **Step 5: Run the full research test file and lint**

Run: `pytest tests/test_research.py -v`
Expected: all tests PASS (find_addresses + merge_addresses + pre-existing research()/cross_check() tests)

Run: `ruff check src/bg_company_lookup/research.py tests/test_research.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/bg_company_lookup/research.py tests/test_research.py
git commit -m "$(cat <<'EOF'
Добавя research.merge_addresses() — обединява регистър + уеб адреси

EOF
)"
```

---

## Task 3: Wire `find_addresses()` + `merge_addresses()` into `/api/report`

**Files:**
- Modify: `src/bg_company_lookup/api.py:22-25` (imports), `src/bg_company_lookup/api.py:464-536` (`api_report`)
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Update `tests/test_api.py`'s existing `/api/report` success-path tests to configure the two new
calls and assert on the new `addresses` field. Replace `test_report_returns_combined_json`
entirely with:

```python
@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_combined_json(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {
        "uic": "106590295",
        "name": "ДЕКОРАМЕТ",
        "address": {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"},
    }
    mock_research_module.research.return_value = {
        "query": "106590295",
        "answer": "уеб контекст",
        "sources": [{"title": "т", "url": "u"}],
    }
    mock_research_module.find_addresses.return_value = {
        "query": "106590295",
        "addresses": [
            {"address": "гр. Пловдив, бул. Тест 5", "context": "офис", "source_url": "https://x.bg"}
        ],
    }
    mock_research_module.cross_check.return_value = "обединен доклад"

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["report"] == "обединен доклад"
    assert body["official_data"]["uic"] == "106590295"
    assert body["web_context_sources"] == [{"title": "т", "url": "u"}]
    assert body["addresses"] == [
        {
            "address": "ул. Първа, 1, София",
            "source": "registry",
            "label": "Адрес на управление",
            "context": None,
            "source_url": None,
            "differs_from_registry": None,
        },
        {
            "address": "гр. Пловдив, бул. Тест 5",
            "source": "web",
            "label": None,
            "context": "офис",
            "source_url": "https://x.bg",
            "differs_from_registry": True,
        },
    ]
    mock_research_module.cross_check.assert_called_once_with(
        "106590295", mock_lookup.return_value, "уеб контекст"
    )
```

Update `test_report_degrades_when_company_not_found` to add the `find_addresses` mock (needed
because this test also reaches the success path, just with `official_data=None`):

```python
@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_degrades_when_company_not_found(mock_lookup, mock_research_module, client):
    mock_lookup.side_effect = CompanyNotFound("не е намерена")
    mock_research_module.research.return_value = {
        "query": "непозната фирма",
        "answer": "уеб контекст",
        "sources": [],
    }
    mock_research_module.find_addresses.return_value = {
        "query": "непозната фирма",
        "addresses": [],
    }
    mock_research_module.cross_check.return_value = "доклад само от уеб"

    resp = client.get("/api/report", query_string={"q": "непозната фирма"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["official_data"] is None
    assert body["addresses"] == []
    assert body["report"] == "доклад само от уеб"
    mock_research_module.cross_check.assert_called_once_with(
        "непозната фирма", None, "уеб контекст"
    )
```

Update `test_report_second_call_is_served_from_cache` to add the `find_addresses` mock (so
`merge_addresses` — which runs for real, not mocked — gets a real dict to work with):

```python
@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_second_call_is_served_from_cache(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
    mock_research_module.research.return_value = {
        "query": "106590295",
        "answer": "уеб контекст",
        "sources": [],
    }
    mock_research_module.find_addresses.return_value = {"query": "106590295", "addresses": []}
    mock_research_module.cross_check.return_value = "доклад"

    first = client.get("/api/report", query_string={"q": "106590295"})
    second = client.get("/api/report", query_string={"q": "  106590295  "})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json() == first.get_json()
    assert mock_lookup.call_count == 1
    assert mock_research_module.research.call_count == 1
    assert mock_research_module.find_addresses.call_count == 1
    assert mock_research_module.cross_check.call_count == 1
```

Add one new test, right after `test_report_returns_502_when_research_fails`, mirroring its
pattern exactly for the new `find_addresses` step:

```python
@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_502_when_find_addresses_fails(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
    mock_research_module.research.return_value = {
        "query": "106590295",
        "answer": "уеб контекст",
        "sources": [],
    }
    mock_research_module.find_addresses.side_effect = ResearchServiceError("Gemini недостъпен")

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k report`
Expected: FAIL — `test_report_returns_combined_json` and the other updated tests fail on missing
`addresses` key in the response body; `test_report_returns_502_when_find_addresses_fails` fails
because `find_addresses` isn't called yet (mock's `side_effect` never triggers, response is 200
not 502).

- [ ] **Step 3: Update `api.py` imports**

Change `src/bg_company_lookup/api.py:22-25` from:

```python
from bg_company_lookup import research
from bg_company_lookup.cache import TTLCache
from bg_company_lookup.core import CompanyNotFound, LookupServiceError, lookup
from bg_company_lookup.research import ResearchServiceError
```

to:

```python
from bg_company_lookup import research
from bg_company_lookup.cache import TTLCache
from bg_company_lookup.core import CompanyNotFound, LookupServiceError, lookup
from bg_company_lookup.research import ResearchServiceError, merge_addresses
```

(`merge_addresses` is imported by name — not called as `research.merge_addresses` — so that it
keeps running for real in tests that `@patch("bg_company_lookup.api.research")` the whole
module, the same way `lookup` is imported and mocked individually rather than through a module
object. It's a pure function with no external calls, so letting it run for real in tests is safe
and avoids having to configure it in every single `/api/report` test.)

- [ ] **Step 4: Update `api_report()` to run `find_addresses()` concurrently and merge results**

Replace `src/bg_company_lookup/api.py:479-535` (from `official_data = None` through the final
`return jsonify(result)`) with:

```python
        official_data = None
        research_result = None
        addresses_result = None
        early_response = None

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            lookup_future = executor.submit(lookup, q)
            research_future = executor.submit(research.research, q)
            addresses_future = executor.submit(research.find_addresses, q)

            try:
                official_data = lookup_future.result()
            except CompanyNotFound:
                official_data = None
            except RuntimeError as e:
                early_response = (jsonify({"error": str(e)}), 500)
            except LookupServiceError as e:
                app.logger.error("companybook.bg upstream error: %s", e)
                early_response = (jsonify({"error": str(e)}), 502)
            except Exception as e:
                app.logger.exception("unexpected error handling /api/report (lookup step)")
                early_response = (jsonify({"error": f"unexpected error: {e}"}), 502)

            try:
                research_result = research_future.result()
            except RuntimeError as e:
                early_response = early_response or (jsonify({"error": str(e)}), 500)
            except ResearchServiceError as e:
                app.logger.error("Gemini API upstream error (research): %s", e)
                early_response = early_response or (jsonify({"error": str(e)}), 502)
            except Exception as e:
                app.logger.exception("unexpected error handling /api/report (research step)")
                early_response = early_response or (
                    jsonify({"error": f"unexpected error: {e}"}),
                    502,
                )

            try:
                addresses_result = addresses_future.result()
            except RuntimeError as e:
                early_response = early_response or (jsonify({"error": str(e)}), 500)
            except ResearchServiceError as e:
                app.logger.error("Gemini API upstream error (find_addresses): %s", e)
                early_response = early_response or (jsonify({"error": str(e)}), 502)
            except Exception as e:
                app.logger.exception(
                    "unexpected error handling /api/report (find_addresses step)"
                )
                early_response = early_response or (
                    jsonify({"error": f"unexpected error: {e}"}),
                    502,
                )

        if early_response:
            return early_response

        try:
            report_text = research.cross_check(q, official_data, research_result["answer"])
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500
        except ResearchServiceError as e:
            app.logger.error("Gemini API upstream error (cross_check): %s", e)
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            app.logger.exception("unexpected error handling /api/report (cross_check step)")
            return jsonify({"error": f"unexpected error: {e}"}), 502

        result = {
            "query": q,
            "report": report_text,
            "official_data": official_data,
            "web_context_sources": research_result["sources"],
            "addresses": merge_addresses(official_data, addresses_result),
        }
        report_cache.set(cache_key, result)
        return jsonify(result)
```

Also update the comment right above the `with concurrent.futures.ThreadPoolExecutor(...)` line
(currently explaining why `lookup()`/`research()` run in parallel) to mention the third task:

```python
        # lookup() (companybook.bg), research() и find_addresses() (и двете Gemini) не зависят
        # едно от друго — изпълняват се успоредно, за да срежем общото latency (важно за да не
        # удряме Render-ия gateway timeout, тъй като cross_check() после добавя още едно
        # последователно Gemini извикване).
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k report`
Expected: all `/api/report` tests PASS, including the new `test_report_returns_502_when_find_addresses_fails`

- [ ] **Step 6: Run the full test suite and lint**

Run: `pytest`
Expected: all tests PASS

Run: `ruff check src/bg_company_lookup/api.py tests/test_api.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/bg_company_lookup/api.py tests/test_api.py
git commit -m "$(cat <<'EOF'
Добавя find_addresses() като трета успоредна стъпка в /api/report

Полето addresses в отговора обединява регистровите адреси с намерените
в уеб, маркирайки уеб адресите, различни от регистъра.
EOF
)"
```

---

## Task 4: UI — "Адреси" card

**Files:**
- Modify: `src/bg_company_lookup/api.py` (inside `INDEX_HTML`)
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Update `test_index_returns_html_page` in `tests/test_api.py` to also assert the new card and
render function are present:

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
    assert "Адреси".encode() in resp.data
    assert b"renderAddresses" in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v -k test_index_returns_html_page`
Expected: FAIL — `assert "Адреси".encode() in resp.data` (and/or the `renderAddresses` assertion)
is False.

- [ ] **Step 3: Add `.badge.warn` and `.address-list` CSS**

In `src/bg_company_lookup/api.py`, inside the `<style>` block, right after the existing:

```css
  .badge.active { background: var(--color-accent); }
```

add:

```css
  .badge.warn { background: var(--color-destructive); }

  ul.address-list {
    list-style: none; padding: 0; margin: 0;
    display: flex; flex-direction: column; gap: 0.6rem;
  }
  ul.address-list li {
    border: 1px solid var(--color-border); border-radius: 8px; padding: 0.6rem 0.75rem;
    font-size: 0.9rem;
  }
  ul.address-list .hint { display: block; margin-top: 0.3rem; }
```

- [ ] **Step 4: Add `renderAddresses()` JS function**

In `src/bg_company_lookup/api.py`, right after the existing `renderSources()` function
(before `form.addEventListener(...)`), add:

```javascript
function renderAddresses(addresses) {
  if (!addresses || addresses.length === 0) {
    return '<p class="empty">Няма намерени адреси.</p>';
  }
  return '<ul class="address-list">' + addresses.map(a => {
    const sourceBadge = a.source === 'web'
      ? '<span class="badge active">уеб</span>'
      : '<span class="badge">регистър</span>';
    const warnBadge = a.differs_from_registry
      ? ' <span class="badge warn">различен от регистъра</span>'
      : '';
    const label = a.label ? '<strong>' + escapeHtml(a.label) + ':</strong> ' : '';
    const context = a.context
      ? '<span class="hint">' + escapeHtml(a.context) + '</span>' : '';
    const link = a.source_url
      ? '<span class="hint"><a href="' + escapeHtml(a.source_url) +
        '" target="_blank" rel="noopener">' + escapeHtml(a.source_url) + '</a></span>'
      : '';
    return '<li>' + sourceBadge + warnBadge + ' ' + label + escapeHtml(a.address) +
      context + link + '</li>';
  }).join('') + '</ul>';
}
```

- [ ] **Step 5: Insert the new card into the result template**

In `src/bg_company_lookup/api.py`, inside `form.addEventListener('submit', ...)`, change:

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

to:

```javascript
    statusEl.innerHTML = '';
    resultEl.innerHTML = `
      <div class="card section">
        <h2>Официални данни от регистъра</h2>
        ${renderOfficialData(body.official_data)}
      </div>
      <div class="card section">
        <h2>Адреси</h2>
        ${renderAddresses(body.addresses)}
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

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_api.py -v -k test_index_returns_html_page`
Expected: PASS

- [ ] **Step 7: Run the full test suite and lint**

Run: `pytest`
Expected: all tests PASS

Run: `ruff check . && ruff format --check .`
Expected: no errors

- [ ] **Step 8: Manual smoke test in a browser**

Run: `python -m bg_company_lookup.api`

Open `http://localhost:5000/`, look up a real EIK (needs `.env` with real API keys), and confirm:
- the "Адреси" card renders between "Официални данни" and "Обединен доклад"
- registry addresses show a plain "регистър" badge
- web-found addresses show an accent "уеб" badge, and a red "различен от регистъра" badge when
  they don't match the registry address
- an empty response (no addresses found either way) shows "Няма намерени адреси."

- [ ] **Step 9: Commit**

```bash
git add src/bg_company_lookup/api.py tests/test_api.py
git commit -m "$(cat <<'EOF'
Добавя карта "Адреси" в UI — показва регистър + уеб адреси разделно

EOF
)"
```

---

## Task 5: Documentation

**Files:**
- Modify: `README.md:63-64`
- Modify: `CLAUDE.md` (research.py bullet)

- [ ] **Step 1: Update `README.md`**

Change (around line 63-64):

```markdown
`{"query", "report", "official_data", "web_context_sources"}`. Ако фирмата не е намерена
в официалния регистър, `official_data` е `null`, а докладът се генерира само от уеб частта.
```

to:

```markdown
`{"query", "report", "official_data", "web_context_sources", "addresses"}`. Ако фирмата не е
намерена в официалния регистър, `official_data` е `null`, а докладът се генерира само от уеб
частта. `addresses` обединява регистровите адреси (адрес на управление + за кореспонденция) с
адреси, намерени чрез уеб търсене (офиси, обекти и др.), маркирайки уеб адресите, различни от
регистъра, с `"differs_from_registry": true`.
```

- [ ] **Step 2: Update `CLAUDE.md`**

In the `research.py` bullet, change:

```markdown
Two functions: `research(query)` does a Google Search–grounded summary; `cross_check(query, official_data, research_answer)` sends both `core.lookup()`'s output and `research()`'s output to Gemini with a fixed prompt that explicitly flags web claims unconfirmed by the official registry.
```

to:

```markdown
Four functions: `research(query)` does a Google Search–grounded summary; `find_addresses(query)` does a separate Google Search–grounded call asking specifically for all known physical addresses of the company, parsed from the model's JSON response (invalid JSON degrades to an empty list rather than raising); `merge_addresses(official_data, web_result)` is a pure function reconciling `core.lookup()`'s registry addresses with `find_addresses()`'s web results, flagging web addresses that don't match any registry address; `cross_check(query, official_data, research_answer)` sends both `core.lookup()`'s output and `research()`'s output to Gemini with a fixed prompt that explicitly flags web claims unconfirmed by the official registry.
```

In the `api.py` bullet, change:

```markdown
`/api/report` calls `core.lookup()` and `research.research()` **concurrently** via `ThreadPoolExecutor` (they don't depend on each other, only `cross_check()` needs both results) to cut latency and reduce the risk of hitting Render's gateway timeout — trade-off: `research()` now runs even when `lookup()` fails first, instead of being skipped.
```

to:

```markdown
`/api/report` calls `core.lookup()`, `research.research()`, and `research.find_addresses()` **concurrently** via `ThreadPoolExecutor` (none of the three depend on each other; `cross_check()` needs `lookup()`+`research()`'s results, `merge_addresses()` needs `lookup()`+`find_addresses()`'s results) to cut latency and reduce the risk of hitting Render's gateway timeout — trade-off: `research()` and `find_addresses()` now run even when `lookup()` fails first, instead of being skipped.
```

- [ ] **Step 3: Run the full test suite one last time**

Run: `pytest`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "$(cat <<'EOF'
Документира addresses полето в /api/report и новите research.py функции

EOF
)"
```
