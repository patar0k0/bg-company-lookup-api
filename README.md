# bg-company-lookup

Малка обвивка около [companybook.bg](https://companybook.bg) API за справки по
българска фирма (по ЕИК или по име) — структуриран профил: адрес, управители,
съдружници, капитал, ДДС, финансови показатели.

## Структура

```
src/bg_company_lookup/
  core.py       — lookup(name_or_eik) + format_profile(); CompanyNotFound / LookupServiceError
  research.py   — research(query) + cross_check(...) през Gemini API; ResearchServiceError
  cache.py      — TTLCache: прост thread-safe in-memory кеш с TTL
  api.py        — Flask обвивка: /api/company, /api/research, /api/report
  cli.py        — CLI: python -m bg_company_lookup.cli <ЕИК/име> [--json]
tests/          — pytest, мокнати HTTP/SDK заявки (не удря реалните API-та)
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
# сложи истинския COMPANYBOOK_API_KEY и си измисли SITE_ACCESS_TOKEN в .env
```

`.env` се чете автоматично (`python-dotenv`) — не е нужно да го export-ваш ръчно.

## CLI

```bash
python -m bg_company_lookup.cli 106590295
python -m bg_company_lookup.cli "Декорамет ЕООД" --json
```

## API сървър

```bash
python -m bg_company_lookup.api
curl "http://localhost:5000/api/company?q=106590295&token=ТВОЯ_ТОКЕН"
```

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
`{"query", "report", "official_data", "web_context_sources", "priority_assessment"}`. Ако
фирмата не е намерена в официалния регистър, `official_data` и `priority_assessment` са
`null`, а докладът се генерира само от уеб частта.

`priority_assessment` е резултат от чисто локална сверка (без допълнителни заявки) на
фирмата срещу 3 фиксирани приоритетни критерия (община, икономическа дейност по КИД-2008,
област на седалище) на конкретна грантова схема — виж `src/bg_company_lookup/priority.py`.

Успешните отговори се кешират in-memory за `REPORT_CACHE_TTL_SECONDS` секунди (по
подразбиране 6 часа) по нормализирано `q` (trim + lowercase) — повторно търсене на
същата фирма е мигновено и не хаби Gemini квота. Грешки не се кешират. Кешът не е
споделен между gunicorn worker процеси (`-w 2`).

Грешки: `400` невалидна/липсваща/твърде дълга заявка, `401` грешен/липсващ
token, `404` фирмата не е намерена (само `/api/company`), `500` липсва API ключ на
сървъра (`COMPANYBOOK_API_KEY` или `GEMINI_API_KEY`), `502` upstream (companybook.bg
или Gemini) е недостъпен. `/api/research` и `/api/report` следват същите кодове.

За продукция — зад gunicorn (Linux; `app` е достъпен в `bg_company_lookup.api`):

```bash
pip install -e ".[prod]"
gunicorn -w 2 -b 0.0.0.0:5000 "bg_company_lookup.api:app"
```

## Деплой на Render

`render.yaml` в repo-то дефинира service-а. Ако вече си създал service-а ръчно
в dashboard-а (не през Blueprint), Render е автодетектнал Poetry от
`pyproject.toml` и е предпълнил Build Command с `poetry install` — това **няма
да работи**, защото проектът не е реален Poetry проект (няма `[tool.poetry]`
секция, build-backend-ът е `setuptools`). Overwrite-ни ръчно двете полета:

| Поле | Стойност |
|---|---|
| Build Command | `pip install -e ".[prod]"` |
| Start Command | `gunicorn -w 2 -b 0.0.0.0:$PORT bg_company_lookup.api:app` |

Плюс environment variables в dashboard-а (не се четат от `.env` — той не е в
git): `COMPANYBOOK_API_KEY`, `SITE_ACCESS_TOKEN`.

За `/api/research` и `/api/report` — и `GEMINI_API_KEY` (безплатен, без карта:
[Google AI Studio](https://aistudio.google.com/apikey)). По избор `GEMINI_MODEL`
(по подразбиране `gemini-3.5-flash-lite`, с автоматичен fallback към
`gemini-3.1-flash-lite` и `gemini-2.5-flash-lite` при 429/изчерпана квота на
конкретния модел).

## Тестове и lint

```bash
pytest
ruff check .
ruff format .
```

Лимити на безплатния companybook.bg план: 100 общи заявки/ден, 30/ден за
финансови данни.
