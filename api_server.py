"""
Малък API сървър за твоя сайт — обвивка около bg_company_lookup.lookup().

Целта: твоят сървър държи истинския COMPANYBOOK_API_KEY скрито (env variable)
и излага един прост, лек ендпойнт, който Claude (или каквото и да е друго)
може да извика само с URL — без custom headers, без нищо сложно:

    GET https://твоя-домейн.com/api/company?q=106590295&token=ТВОЯ_ТАЕН_ТОКЕН
    GET https://твоя-домейн.com/api/company?q=Декорамет+ЕООД&token=ТВОЯ_ТАЕН_ТОКЕН

Отговорът е чист JSON — същият dict, който връща lookup() от bg_company_lookup.py.

--- Как да го пуснеш ---

1. pip install flask requests
2. Сложи два environment variable-а на сървъра си:
     COMPANYBOOK_API_KEY = ключът от companybook.bg (истинският, секретният)
     SITE_ACCESS_TOKEN   = измисли си произволен дълъг таен низ — това е
                            твоята "ключалка" на този ендпойнт, за да не може
                            кой да е да го вика вместо теб
3. Пусни го: python api_server.py  (по подразбиране слуша на порт 5000)
4. Качи го на нещо просто и безплатно за начало — Render.com, Railway.app,
   PythonAnywhere — всички поддържат Flask "из кутията" с env variables в
   техния dashboard, не ти трябва сървър, който сам поддържаш.
5. Дай ми готовия публичен URL + token и ще преправя Skill-а да го вика.

--- Сигурност ---

- token-ът пази ендпойнта от чужди хора, но пак минава в чист текст в URL —
  напълно ок за личен инструмент, не го слагай в публично repo/сайт.
- Ако искаш по-сериозна защита по-нататък (rate limiting, HTTPS-only, IP
  whitelist), кажи ми и ще го добавя — за начало това е достатъчно.
"""

import os
from flask import Flask, request, jsonify

from bg_company_lookup import lookup, CompanyNotFound

app = Flask(__name__)

SITE_ACCESS_TOKEN = os.environ.get("SITE_ACCESS_TOKEN")


@app.route("/api/company")
def company():
    if SITE_ACCESS_TOKEN and request.args.get("token") != SITE_ACCESS_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    q = request.args.get("q")
    if not q:
        return jsonify({"error": "missing 'q' parameter (name or ЕИК)"}), 400

    include_financial = request.args.get("financial", "true").lower() != "false"

    try:
        result = lookup(q, include_financial=include_financial)
        return jsonify(result)
    except CompanyNotFound as e:
        return jsonify({"error": str(e)}), 404
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:  # ако companybook.bg е бавен/недостъпен и т.н.
        return jsonify({"error": f"unexpected error: {e}"}), 502


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
