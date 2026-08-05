# Gemini Research + Report Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /api/research` (Gemini + Google Search grounding web summary) and `GET /api/report` (official registry data cross-checked against web research) to the existing Flask API, without touching `/api/company`.

**Architecture:** New `src/bg_company_lookup/research.py` module (mirrors `core.py`'s style: plain functions + typed exceptions) wraps the `google-genai` SDK. `api.py` gets a small internal `_validate_request()` helper (token/`q` validation, reused by the two new routes only) and two new routes that call `core.lookup()` and the new `research` module, mapping exceptions to HTTP codes the same way `/api/company` already does.

**Tech Stack:** Flask, `google-genai` Python SDK (Gemini API, `gemini-flash-lite-latest` model, Google Search grounding tool), pytest + `unittest.mock`.

---

## File Structure

- Create: `src/bg_company_lookup/research.py` — `research()`, `cross_check()`, `ResearchServiceError`
- Modify: `src/bg_company_lookup/api.py` — add `_validate_request()` helper + two new routes (do not touch the existing `/api/company` route or `main`/`app` module-level code)
- Modify: `pyproject.toml` — add `google-genai` dependency
- Modify: `.env.example` — add `GEMINI_API_KEY`, `GEMINI_MODEL`
- Modify: `render.yaml` — add `GEMINI_API_KEY` env var
- Modify: `README.md` — document the two new routes and env vars
- Create: `tests/test_research.py`
- Modify: `tests/test_api.py` — add tests for the two new routes

---

### Task 1: Add `google-genai` dependency

**Files:**
- Modify: `pyproject.toml:6-10`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, change:

```toml
dependencies = [
    "requests>=2.31",
    "flask>=3.0",
    "python-dotenv>=1.0",
]
```

to:

```toml
dependencies = [
    "requests>=2.31",
    "flask>=3.0",
    "python-dotenv>=1.0",
    "google-genai>=1.0",
]
```

- [ ] **Step 2: Reinstall the package in editable mode**

Run: `pip install -e ".[dev]"`
Expected: `google-genai` (and its dependencies) installed successfully, no errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "Добавя google-genai като dependency"
```

---

### Task 2: `research.py` skeleton — client/model helpers + missing-API-key error

**Files:**
- Create: `src/bg_company_lookup/research.py`
- Test: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_research.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from bg_company_lookup.research import ResearchServiceError, cross_check, research


def _mock_response(text="обобщение", with_sources=True):
    response = MagicMock()
    response.text = text
    if with_sources:
        web = MagicMock()
        web.title = "Пример Източник"
        web.uri = "https://example.bg/article"
        chunk = MagicMock()
        chunk.web = web
        metadata = MagicMock()
        metadata.grounding_chunks = [chunk]
        candidate = MagicMock()
        candidate.grounding_metadata = metadata
        response.candidates = [candidate]
    else:
        response.candidates = []
    return response


def test_research_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        research("тестова тема", api_key=None)


def test_cross_check_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        cross_check("тема", {"name": "Тест"}, "уеб отговор", api_key=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bg_company_lookup.research'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/bg_company_lookup/research.py`:

```python
"""
Малка обвивка около Gemini API (google-genai SDK) за:
  - research(query)          — уеб търсене с Google Search grounding, обобщено
                                на български, с цитирани източници.
  - cross_check(query, ...)  — кръстосана проверка на официални регистърни данни
                                срещу уеб резултати.

Безплатен tier (2026): Flash/Flash-Lite моделите поддържат Google Search grounding
безплатно (5000 grounded заявки/месец), без нужда от карта — API ключ се взима от
https://aistudio.google.com/apikey
"""

from __future__ import annotations

import json
import os

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-flash-lite-latest"

CROSS_CHECK_PROMPT_TEMPLATE = """Официални регистърни данни: {company_json}
Резултати от уеб търсене: {research_answer}

Сравни ги. Ако уеб резултатите твърдят нещо (напр. оборот, брой служители, финансово \
състояние), което НЕ се потвърждава от официалните данни — отбележи го изрично като \
непотвърдено, не го представяй като факт. Дай един обединен доклад на български, \
разграничавайки ясно 'потвърдено от регистъра' от 'според уеб източници, непотвърдено'."""


class ResearchServiceError(Exception):
    """Gemini API недостъпен/грешка при извикване (аналог на LookupServiceError)."""


def _client(api_key: str | None) -> genai.Client:
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Липсва API ключ. Подай го като аргумент или сложи GEMINI_API_KEY в env."
        )
    return genai.Client(api_key=api_key)


def _model_name(model: str | None) -> str:
    return model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


def _extract_sources(response) -> list[dict]:
    sources = []
    for candidate in getattr(response, "candidates", None) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        chunks = getattr(metadata, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            uri = getattr(web, "uri", None)
            if not uri:
                continue
            sources.append({"title": getattr(web, "title", None), "url": uri})
    return sources


def research(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    raise NotImplementedError


def cross_check(
    query: str,
    official_data: dict | None,
    research_answer: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    _client(api_key)
    raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research.py -v`
Expected: `test_research_requires_api_key` and `test_cross_check_requires_api_key` PASS (both raise `RuntimeError` before reaching `NotImplementedError` — `research()` needs a one-line fix first, see below).

Fix `research()` so it also calls `_client()` before anything else:

```python
def research(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    _client(api_key)
    raise NotImplementedError
```

Run again: `pytest tests/test_research.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bg_company_lookup/research.py tests/test_research.py
git commit -m "Добавя research.py скелет с client/model helpers и RuntimeError при липсващ GEMINI_API_KEY"
```

---

### Task 3: Implement `research()` (Google Search grounding)

**Files:**
- Modify: `src/bg_company_lookup/research.py`
- Test: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_research.py`:

```python
@patch("bg_company_lookup.research.genai.Client")
def test_research_returns_answer_and_sources(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response()

    result = research("тестова тема", api_key="fake-key")

    assert result["query"] == "тестова тема"
    assert result["answer"] == "обобщение"
    assert result["sources"] == [
        {"title": "Пример Източник", "url": "https://example.bg/article"}
    ]


@patch("bg_company_lookup.research.genai.Client")
def test_research_returns_empty_sources_when_no_grounding(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        with_sources=False
    )

    result = research("тестова тема", api_key="fake-key")

    assert result["sources"] == []


@patch("bg_company_lookup.research.genai.Client")
def test_research_raises_service_error_on_sdk_failure(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.side_effect = RuntimeError("boom")

    with pytest.raises(ResearchServiceError):
        research("тестова тема", api_key="fake-key")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research.py -v`
Expected: the 3 new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `research()`**

In `src/bg_company_lookup/research.py`, replace the `research()` stub with:

```python
def research(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    """
    Уеб търсене през Gemini (Google Search grounding) по зададена тема.

    Връща: {"query": ..., "answer": ..., "sources": [{"title": ..., "url": ...}, ...]}

    Хвърля:
        RuntimeError         — липсва GEMINI_API_KEY
        ResearchServiceError — Gemini API недостъпен/грешка при извикване
    """
    client = _client(api_key)
    prompt = (
        "Обобщи резултатите от търсене по следната тема на български език, "
        "структурирано (с подходящи секции/точки), и цитирай източниците в края:\n\n"
        f"{query}"
    )
    try:
        response = client.models.generate_content(
            model=_model_name(model),
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
    except Exception as e:
        raise ResearchServiceError(f"Gemini API недостъпен: {e}") from e

    return {
        "query": query,
        "answer": response.text,
        "sources": _extract_sources(response),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research.py -v`
Expected: all tests so far PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bg_company_lookup/research.py tests/test_research.py
git commit -m "Имплементира research() с Google Search grounding"
```

---

### Task 4: Implement `cross_check()`

**Files:**
- Modify: `src/bg_company_lookup/research.py`
- Test: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_research.py`:

```python
@patch("bg_company_lookup.research.genai.Client")
def test_cross_check_returns_report_text(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text="обединен доклад", with_sources=False
    )

    report = cross_check("тема", {"name": "Тест"}, "уеб отговор", api_key="fake-key")

    assert report == "обединен доклад"


@patch("bg_company_lookup.research.genai.Client")
def test_cross_check_handles_company_not_found(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text="доклад без регистърни данни", with_sources=False
    )

    report = cross_check("тема", None, "уеб отговор", api_key="fake-key")

    assert report == "доклад без регистърни данни"
    call_kwargs = mock_client_cls.return_value.models.generate_content.call_args.kwargs
    assert "не е намерена в официалния регистър" in call_kwargs["contents"]


@patch("bg_company_lookup.research.genai.Client")
def test_cross_check_raises_service_error_on_sdk_failure(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.side_effect = RuntimeError("boom")

    with pytest.raises(ResearchServiceError):
        cross_check("тема", {"name": "Тест"}, "уеб отговор", api_key="fake-key")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research.py -v`
Expected: the 3 new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `cross_check()`**

In `src/bg_company_lookup/research.py`, replace the `cross_check()` stub with:

```python
def cross_check(
    query: str,
    official_data: dict | None,
    research_answer: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """
    Кръстосана проверка: праща официалните регистърни данни + уеб резултатите на
    Gemini и връща обединен доклад на български (текст), разграничаващ потвърдени
    от непотвърдени твърдения.

    Хвърля:
        RuntimeError         — липсва GEMINI_API_KEY
        ResearchServiceError — Gemini API недостъпен/грешка при извикване
    """
    client = _client(api_key)
    company_json = (
        json.dumps(official_data, ensure_ascii=False, indent=2)
        if official_data is not None
        else "(фирмата не е намерена в официалния регистър)"
    )
    prompt = CROSS_CHECK_PROMPT_TEMPLATE.format(
        company_json=company_json, research_answer=research_answer
    )
    try:
        response = client.models.generate_content(model=_model_name(model), contents=prompt)
    except Exception as e:
        raise ResearchServiceError(f"Gemini API недостъпен: {e}") from e

    return response.text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research.py -v`
Expected: all tests PASS (9 total).

- [ ] **Step 5: Commit**

```bash
git add src/bg_company_lookup/research.py tests/test_research.py
git commit -m "Имплементира cross_check() за кръстосана проверка на регистър срещу уеб данни"
```

---

### Task 5: `/api/research` route

**Files:**
- Modify: `src/bg_company_lookup/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_api.py`, add to the imports at the top:

```python
from bg_company_lookup.research import ResearchServiceError
```

Append these tests to the file:

```python
def test_research_requires_q_param(client):
    resp = client.get("/api/research")
    assert resp.status_code == 400


def test_research_rejects_missing_token_when_configured(protected_client):
    resp = protected_client.get("/api/research", query_string={"q": "оборот на фирмите в БГ"})
    assert resp.status_code == 401


@patch("bg_company_lookup.api.research")
def test_research_returns_answer_json(mock_research_module, client):
    mock_research_module.research.return_value = {
        "query": "оборот",
        "answer": "текст",
        "sources": [],
    }

    resp = client.get("/api/research", query_string={"q": "оборот"})

    assert resp.status_code == 200
    assert resp.get_json()["answer"] == "текст"


@patch("bg_company_lookup.api.research")
def test_research_returns_500_on_missing_api_key(mock_research_module, client):
    mock_research_module.research.side_effect = RuntimeError("Липсва API ключ")

    resp = client.get("/api/research", query_string={"q": "оборот"})

    assert resp.status_code == 500


@patch("bg_company_lookup.api.research")
def test_research_returns_502_on_upstream_error(mock_research_module, client):
    mock_research_module.research.side_effect = ResearchServiceError("Gemini недостъпен")

    resp = client.get("/api/research", query_string={"q": "оборот"})

    assert resp.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k research`
Expected: FAIL — `/api/research` returns 404 (route doesn't exist yet).

- [ ] **Step 3: Implement the route**

In `src/bg_company_lookup/api.py`, add to the imports (below the existing `from bg_company_lookup.core import ...` line):

```python
from bg_company_lookup import research
from bg_company_lookup.research import ResearchServiceError
```

Inside `create_app()`, add this helper right before the existing `@app.route("/api/company")` def (do not modify the `/api/company` route itself):

```python
    def _validate_request(q_description: str) -> tuple[str, None] | tuple[None, tuple]:
        token = app.config["ACCESS_TOKEN"]
        if token and request.args.get("token") != token:
            return None, (jsonify({"error": "unauthorized"}), 401)

        q = (request.args.get("q") or "").strip()
        if not q:
            return None, (jsonify({"error": f"missing 'q' parameter ({q_description})"}), 400)
        if len(q) > MAX_QUERY_LENGTH:
            return None, (
                jsonify({"error": f"'q' е твърде дълго (макс. {MAX_QUERY_LENGTH} символа)"}),
                400,
            )

        return q, None
```

Then, after the existing `/api/company` route (and before `@app.route("/health")`), add:

```python
    @app.route("/api/research")
    def api_research():
        q, error = _validate_request("тема за търсене")
        if error:
            return error

        try:
            result = research.research(q)
            return jsonify(result)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500
        except ResearchServiceError as e:
            app.logger.error("Gemini API upstream error: %s", e)
            return jsonify({"error": str(e)}), 502
        except Exception as e:  # неочаквана грешка — не изтичаме stack trace към клиента
            app.logger.exception("unexpected error handling /api/research")
            return jsonify({"error": f"unexpected error: {e}"}), 502
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k research`
Expected: all 5 tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: all tests PASS, including the existing `/api/company` tests (unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/bg_company_lookup/api.py tests/test_api.py
git commit -m "Добавя GET /api/research route"
```

---

### Task 6: `/api/report` route

**Files:**
- Modify: `src/bg_company_lookup/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_report_requires_q_param(client):
    resp = client.get("/api/report")
    assert resp.status_code == 400


def test_report_rejects_missing_token_when_configured(protected_client):
    resp = protected_client.get("/api/report", query_string={"q": "106590295"})
    assert resp.status_code == 401


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_combined_json(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
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
    mock_research_module.cross_check.assert_called_once_with(
        "106590295", {"uic": "106590295", "name": "ДЕКОРАМЕТ"}, "уеб контекст"
    )


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_degrades_when_company_not_found(mock_lookup, mock_research_module, client):
    mock_lookup.side_effect = CompanyNotFound("не е намерена")
    mock_research_module.research.return_value = {
        "query": "непозната фирма",
        "answer": "уеб контекст",
        "sources": [],
    }
    mock_research_module.cross_check.return_value = "доклад само от уеб"

    resp = client.get("/api/report", query_string={"q": "непозната фирма"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["official_data"] is None
    assert body["report"] == "доклад само от уеб"
    mock_research_module.cross_check.assert_called_once_with(
        "непозната фирма", None, "уеб контекст"
    )


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_500_on_missing_companybook_key(mock_lookup, mock_research_module, client):
    mock_lookup.side_effect = RuntimeError("Липсва API ключ")

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 500
    mock_research_module.research.assert_not_called()


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_502_when_lookup_upstream_fails(mock_lookup, mock_research_module, client):
    mock_lookup.side_effect = LookupServiceError("companybook.bg недостъпен")

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 502
    mock_research_module.research.assert_not_called()


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_502_when_research_fails(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
    mock_research_module.research.side_effect = ResearchServiceError("Gemini недостъпен")

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 502


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_502_when_cross_check_fails(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
    mock_research_module.research.return_value = {
        "query": "106590295",
        "answer": "уеб контекст",
        "sources": [],
    }
    mock_research_module.cross_check.side_effect = ResearchServiceError("Gemini недостъпен")

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k report`
Expected: FAIL — `/api/report` returns 404 (route doesn't exist yet).

- [ ] **Step 3: Implement the route**

In `src/bg_company_lookup/api.py`, after the `/api/research` route added in Task 5 (and still before `@app.route("/health")`), add:

```python
    @app.route("/api/report")
    def api_report():
        q, error = _validate_request("name or ЕИК")
        if error:
            return error

        try:
            official_data = lookup(q)
        except CompanyNotFound:
            official_data = None
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500
        except LookupServiceError as e:
            app.logger.error("companybook.bg upstream error: %s", e)
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            app.logger.exception("unexpected error handling /api/report (lookup step)")
            return jsonify({"error": f"unexpected error: {e}"}), 502

        try:
            research_result = research.research(q)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500
        except ResearchServiceError as e:
            app.logger.error("Gemini API upstream error (research): %s", e)
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            app.logger.exception("unexpected error handling /api/report (research step)")
            return jsonify({"error": f"unexpected error: {e}"}), 502

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

        return jsonify(
            {
                "query": q,
                "report": report_text,
                "official_data": official_data,
                "web_context_sources": research_result["sources"],
            }
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k report`
Expected: all 7 tests PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS (existing `/api/company`/`/health` tests, `test_research.py`, and all new `test_api.py` tests).

- [ ] **Step 6: Commit**

```bash
git add src/bg_company_lookup/api.py tests/test_api.py
git commit -m "Добавя GET /api/report route (регистър + уеб research + cross-check)"
```

---

### Task 7: Config and docs

**Files:**
- Modify: `.env.example`
- Modify: `render.yaml`
- Modify: `README.md`

- [ ] **Step 1: Update `.env.example`**

Change:

```
COMPANYBOOK_API_KEY=
SITE_ACCESS_TOKEN=
PORT=5000
```

to:

```
COMPANYBOOK_API_KEY=
SITE_ACCESS_TOKEN=
GEMINI_API_KEY=
GEMINI_MODEL=
PORT=5000
```

- [ ] **Step 2: Update `render.yaml`**

Change the `envVars` list from:

```yaml
    envVars:
      - key: PYTHON_VERSION
        value: 3.12.10
      - key: COMPANYBOOK_API_KEY
        sync: false
      - key: SITE_ACCESS_TOKEN
        sync: false
```

to:

```yaml
    envVars:
      - key: PYTHON_VERSION
        value: 3.12.10
      - key: COMPANYBOOK_API_KEY
        sync: false
      - key: SITE_ACCESS_TOKEN
        sync: false
      - key: GEMINI_API_KEY
        sync: false
```

- [ ] **Step 3: Update `README.md`**

In the "Структура" section, change:

```
src/bg_company_lookup/
  core.py   — lookup(name_or_eik) + format_profile(); CompanyNotFound / LookupServiceError
  api.py    — Flask обвивка: GET /api/company?q=...&token=...
  cli.py    — CLI: python -m bg_company_lookup.cli <ЕИК/име> [--json]
tests/      — pytest, мокнати HTTP заявки (не удря реалния API)
```

to:

```
src/bg_company_lookup/
  core.py       — lookup(name_or_eik) + format_profile(); CompanyNotFound / LookupServiceError
  research.py   — research(query) + cross_check(...) през Gemini API; ResearchServiceError
  api.py        — Flask обвивка: /api/company, /api/research, /api/report
  cli.py        — CLI: python -m bg_company_lookup.cli <ЕИК/име> [--json]
tests/          — pytest, мокнати HTTP/SDK заявки (не удря реалните API-та)
```

In the "API сървър" section, after the existing `curl` example for `/api/company`, add:

```markdown
### /api/research — уеб search summary през Gemini

```bash
curl "http://localhost:5000/api/research?q=последни+новини+за+българската+икономика&token=ТВОЯ_ТОКЕН"
```

Връща `{"query", "answer", "sources"}` — `answer` е обобщение на български от Gemini
с включен Google Search grounding tool, `sources` е списък от `{"title", "url"}`.

### /api/report — регистърни данни + уеб кръстосана проверка

```bash
curl "http://localhost:5000/api/report?q=106590295&token=ТВОЯ_ТОКЕН"
```

Извиква вътрешно и `/api/company`-логиката (`core.lookup`), и `/api/research`-логиката,
после праща двата резултата на Gemini да ги сравни — всичко от уеб search, което НЕ се
потвърждава от официалния регистър, се отбелязва изрично като непотвърдено. Връща
`{"query", "report", "official_data", "web_context_sources"}`. Ако фирмата не е намерена
в официалния регистър, `official_data` е `null`, а докладът се генерира само от уеб частта.
```

At the end of the "Грешки" paragraph, add a note:

```markdown
`/api/research` и `/api/report` използват същите кодове (400/401/502), плюс `500` при
липсващ `GEMINI_API_KEY`.
```

In the "Деплой на Render" table area, after the existing environment variables sentence, add:

```markdown
За `/api/research` и `/api/report` — и `GEMINI_API_KEY` (безплатен, без карта:
[Google AI Studio](https://aistudio.google.com/apikey)). По избор `GEMINI_MODEL`
(по подразбиране `gemini-flash-lite-latest`).
```

- [ ] **Step 4: Commit**

```bash
git add .env.example render.yaml README.md
git commit -m "Документира /api/research и /api/report, добавя GEMINI_API_KEY config"
```

---

### Task 8: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS, including `test_core.py`, `test_cli.py`, `test_api.py`, `test_research.py`.

- [ ] **Step 2: Run lint**

Run: `ruff check .`
Expected: no errors. Fix any reported issues (likely import order/formatting in `research.py` or `api.py`) and re-run.

Run: `ruff format --check .`
Expected: no reformatting needed. If it reports files needing formatting, run `ruff format .` and re-run the test suite to confirm nothing broke.

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "Lint fixes"
```

(Skip this step if `ruff check`/`ruff format --check` reported no issues.)

---

## Self-Review Notes

- **Spec coverage:** both routes, both error-handling paths (fail-closed for `/api/report`'s research/cross-check steps, graceful `CompanyNotFound` degrade for the lookup step), shared auth model, `GEMINI_API_KEY`/`GEMINI_MODEL` config, `google-genai` dependency, README/`.env.example`/`render.yaml` updates, and tests for success/missing-token/missing-q/upstream-error for both routes are all covered by Tasks 1–7.
- **Placeholder scan:** no TBD/TODO left; the only intentional stub (`NotImplementedError` in Task 2) is filled in by Tasks 3–4 within the same file before the plan moves on.
- **Type consistency:** `research()` always returns `{"query", "answer", "sources"}`; `/api/report` reads `research_result["answer"]` and `research_result["sources"]` — matches. `cross_check()` returns a plain `str`, used directly as `report` in the response — matches. `_validate_request()` returns `(q, None)` or `(None, error_tuple)` and both new routes unpack it the same way.
