# bg-company-lookup

Малка обвивка около [companybook.bg](https://companybook.bg) API за справки по
българска фирма (по ЕИК или по име) — структуриран профил: адрес, управители,
съдружници, капитал, ДДС, финансови показатели.

## Файлове

- `bg_company_lookup.py` — ядрото: функцията `lookup(name_or_eik)` + CLI режим.
- `api_server.py` — Flask обвивка, излага `GET /api/company?q=...&token=...` за
  извикване от друго приложение (напр. Claude skill), без да разкрива реалния
  companybook ключ.
- `requirements.txt` — `flask`, `requests`, `gunicorn`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# сложи истинския COMPANYBOOK_API_KEY и си измисли SITE_ACCESS_TOKEN в .env
```

## CLI употреба

```bash
python bg_company_lookup.py 106590295
python bg_company_lookup.py "Декорамет ЕООД" --json
```

## API сървър

```bash
python api_server.py
curl "http://localhost:5000/api/company?q=106590295&token=ТВОЯ_ТОКЕН"
```

Лимити на безплатния companybook.bg план: 100 общи заявки/ден, 30/ден за
финансови данни.
