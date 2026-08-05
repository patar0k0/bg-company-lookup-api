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

INDEX_HTML = """<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8">
<title>BG Company Lookup</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto;
    padding: 0 1rem; line-height: 1.5;
  }
  h1 { font-size: 1.4rem; }
  form { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
  input[type=text], input[type=password] {
    flex: 1; min-width: 200px; padding: 0.5rem; font-size: 1rem;
  }
  button { padding: 0.5rem 1rem; font-size: 1rem; cursor: pointer; }
  #status { margin: 1rem 0; font-style: italic; }
  .error { color: #c00; font-weight: bold; }
  .section { margin-bottom: 1.5rem; padding: 1rem; border: 1px solid #888; border-radius: 6px; }
  .section h2 { margin-top: 0; font-size: 1.1rem; }
  ul { padding-left: 1.2rem; }
  a { word-break: break-all; }
</style>
</head>
<body>
<h1>Справка за българска фирма</h1>
<form id="lookup-form">
  <input type="text" id="q" placeholder="ЕИК или име на фирма" required>
  <input type="password" id="token" placeholder="token">
  <button type="submit">Провери фирма</button>
</form>
<div id="status"></div>
<div id="result"></div>

<script>
const form = document.getElementById('lookup-form');
const qInput = document.getElementById('q');
const tokenInput = document.getElementById('token');
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');

tokenInput.value = localStorage.getItem('bg_company_lookup_token') || '';

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function renderOfficialData(data) {
  if (!data) {
    return '<p><em>Фирмата не е намерена в официалния регистър.</em></p>';
  }
  const managers = (data.managers || []).map(m => escapeHtml(m.name || '?')).join(', ') || '—';
  return `
    <p><strong>${escapeHtml(data.name || '(без име)')}</strong></p>
    <p>ЕИК: ${escapeHtml(data.uic)} | Статус: ${escapeHtml(data.status)}</p>
    <p>Управители: ${managers}</p>
  `;
}

function renderSources(sources) {
  if (!sources || sources.length === 0) return '<p><em>Няма източници.</em></p>';
  return '<ul>' + sources.map(s => {
    const label = escapeHtml(s.title || s.url);
    const href = escapeHtml(s.url);
    return `<li><a href="${href}" target="_blank" rel="noopener">${label}</a></li>`;
  }).join('') + '</ul>';
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = qInput.value.trim();
  const token = tokenInput.value.trim();
  localStorage.setItem('bg_company_lookup_token', token);

  statusEl.textContent = 'Зареждане... (може да отнеме до минута)';
  resultEl.innerHTML = '';

  try {
    const url = '/api/report?q=' + encodeURIComponent(q) + '&token=' + encodeURIComponent(token);
    const resp = await fetch(url);
    const body = await resp.json();

    if (!resp.ok) {
      statusEl.innerHTML = '<span class="error">Грешка (' + resp.status + '): ' +
        escapeHtml(body.error || 'неизвестна грешка') + '</span>';
      return;
    }

    statusEl.textContent = '';
    resultEl.innerHTML = `
      <div class="section">
        <h2>Официални данни от регистъра</h2>
        ${renderOfficialData(body.official_data)}
      </div>
      <div class="section">
        <h2>Обединен доклад</h2>
        <div>${escapeHtml(body.report).replace(/\\n/g, '<br>')}</div>
      </div>
      <div class="section">
        <h2>Уеб източници</h2>
        ${renderSources(body.web_context_sources)}
      </div>
    `;
  } catch (err) {
    statusEl.innerHTML = '<span class="error">Грешка при връзка със сървъра: ' +
      escapeHtml(err.message) + '</span>';
  }
});
</script>
</body>
</html>
"""


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

    @app.route("/")
    def index():
        return INDEX_HTML

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
