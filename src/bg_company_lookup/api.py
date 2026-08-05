"""
Малък API сървър — обвивка около bg_company_lookup.core.lookup().

Целта: твоят сървър държи истинския COMPANYBOOK_API_KEY скрито (env variable)
и излага един прост, лек ендпойнт, който може да се вика само с URL:

    GET https://твоя-домейн.com/api/company?q=106590295&token=ТВОЯ_ТАЕН_ТОКЕН
    GET https://твоя-домейн.com/api/company?q=Декорамет+ЕООД&token=ТВОЯ_ТАЕН_ТОКЕН

token-ът пази ендпойнта от чужди хора, но пак минава в чист текст в URL —
напълно ок за личен инструмент, не го слагай в публично repo/сайт.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from bg_company_lookup import research
from bg_company_lookup.core import CompanyNotFound, LookupServiceError, lookup
from bg_company_lookup.research import ResearchServiceError

MAX_QUERY_LENGTH = 200

load_dotenv()


def create_app(access_token: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["ACCESS_TOKEN"] = access_token

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

    @app.route("/api/company")
    def company():
        token = app.config["ACCESS_TOKEN"]
        if token and request.args.get("token") != token:
            return jsonify({"error": "unauthorized"}), 401

        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"error": "missing 'q' parameter (name or ЕИК)"}), 400
        if len(q) > MAX_QUERY_LENGTH:
            return jsonify({"error": f"'q' е твърде дълго (макс. {MAX_QUERY_LENGTH} символа)"}), 400

        include_financial = request.args.get("financial", "true").lower() != "false"

        try:
            result = lookup(q, include_financial=include_financial)
            return jsonify(result)
        except CompanyNotFound as e:
            return jsonify({"error": str(e)}), 404
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500
        except LookupServiceError as e:
            app.logger.error("companybook.bg upstream error: %s", e)
            return jsonify({"error": str(e)}), 502
        except Exception as e:  # неочаквана грешка — не изтичаме stack trace към клиента
            app.logger.exception("unexpected error handling /api/company")
            return jsonify({"error": f"unexpected error: {e}"}), 502

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

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    return app


def main() -> None:
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# gunicorn/flask run очакват модулно ниво `app`
app = create_app(access_token=os.environ.get("SITE_ACCESS_TOKEN"))

if __name__ == "__main__":
    main()
