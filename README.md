# bg-company-lookup

Малка обвивка около [companybook.bg](https://companybook.bg) API за справки по
българска фирма (по ЕИК или по име) — структуриран профил: адрес, управители,
съдружници, капитал, ДДС, финансови показатели.

## Структура

```
src/bg_company_lookup/
  core.py   — lookup(name_or_eik) + format_profile(); CompanyNotFound / LookupServiceError
  api.py    — Flask обвивка: GET /api/company?q=...&token=...
  cli.py    — CLI: python -m bg_company_lookup.cli <ЕИК/име> [--json]
tests/      — pytest, мокнати HTTP заявки (не удря реалния API)
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

Грешки: `400` невалидна/липсваща/твърде дълга заявка, `401` грешен/липсващ
token, `404` фирмата не е намерена, `500` липсва API ключ на сървъра, `502`
companybook.bg е недостъпен.

За продукция — зад gunicorn (Linux; `app` е достъпен в `bg_company_lookup.api`):

```bash
pip install -e ".[prod]"
gunicorn -w 2 -b 0.0.0.0:5000 "bg_company_lookup.api:app"
```

## Тестове и lint

```bash
pytest
ruff check .
ruff format .
```

Лимити на безплатния companybook.bg план: 100 общи заявки/ден, 30/ден за
финансови данни.
