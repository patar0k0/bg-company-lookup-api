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

import concurrent.futures
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from bg_company_lookup import priority, research
from bg_company_lookup.cache import TTLCache
from bg_company_lookup.core import CompanyNotFound, LookupServiceError, lookup
from bg_company_lookup.research import ResearchServiceError

MAX_QUERY_LENGTH = 200
REPORT_CACHE_TTL_SECONDS = int(os.environ.get("REPORT_CACHE_TTL_SECONDS", 6 * 60 * 60))

load_dotenv()

INDEX_HTML = """<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BG Company Lookup</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap">
<style>
  :root {
    color-scheme: light dark;
    --color-primary: #1E3A5F;
    --color-secondary: #2563EB;
    --color-accent: #059669;
    --color-background: #F8FAFC;
    --color-surface: #FFFFFF;
    --color-foreground: #0F172A;
    --color-muted-fg: #55627A;
    --color-border: #E4E7EB;
    --color-destructive: #DC2626;
    --color-destructive-bg: #FEF2F2;
    --color-ring: #1E3A5F;
    --font-heading: 'Poppins', system-ui, sans-serif;
    --font-body: 'Open Sans', system-ui, sans-serif;
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --color-primary: #3B82F6;
      --color-secondary: #60A5FA;
      --color-accent: #10B981;
      --color-background: #0B1220;
      --color-surface: #131B2C;
      --color-foreground: #E7ECF5;
      --color-muted-fg: #97A3BD;
      --color-border: #263049;
      --color-destructive: #F87171;
      --color-destructive-bg: #2A1416;
      --color-ring: #60A5FA;
    }
  }

  * { box-sizing: border-box; }

  body {
    font-family: var(--font-body);
    background: var(--color-background);
    color: var(--color-foreground);
    max-width: 720px;
    margin: 0 auto;
    padding: 1.5rem 1rem 2rem;
    line-height: 1.5;
    font-size: 15px;
  }

  h1 {
    font-family: var(--font-heading);
    font-weight: 600;
    font-size: 1.35rem;
    margin: 0 0 0.3rem;
  }

  .subtitle {
    color: var(--color-muted-fg);
    margin: 0 0 1.25rem;
    font-size: 0.9rem;
  }

  .card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    padding: 1rem;
    margin-bottom: 1rem;
  }

  label {
    display: block;
    font-weight: 600;
    font-size: 0.85rem;
    margin-bottom: 0.3rem;
  }

  .field { margin-bottom: 0.75rem; }
  .field:last-of-type { margin-bottom: 0.9rem; }

  input[type=text], input[type=password] {
    width: 100%;
    font-family: var(--font-body);
    font-size: 0.95rem;
    padding: 0.5rem 0.65rem;
    border: 1px solid var(--color-border);
    border-radius: 8px;
    background: var(--color-background);
    color: var(--color-foreground);
  }

  input:focus-visible {
    outline: 2px solid var(--color-ring);
    outline-offset: 1px;
  }

  .hint {
    font-size: 0.8rem;
    color: var(--color-muted-fg);
    margin-top: 0.3rem;
    font-weight: 400;
  }

  button {
    width: 100%;
    font-family: var(--font-heading);
    font-weight: 600;
    font-size: 0.95rem;
    padding: 0.6rem 1rem;
    border: none;
    border-radius: 8px;
    background: var(--color-accent);
    color: #fff;
    cursor: pointer;
    transition: opacity 150ms ease-out;
  }

  button:hover:not(:disabled) { opacity: 0.9; }
  button:focus-visible { outline: 2px solid var(--color-ring); outline-offset: 2px; }
  button:disabled { opacity: 0.6; cursor: not-allowed; }

  #status { margin: 0.75rem 0; font-size: 0.85rem; color: var(--color-muted-fg); }

  .error-box {
    background: var(--color-destructive-bg);
    border: 1px solid var(--color-destructive);
    color: var(--color-destructive);
    border-radius: 8px;
    padding: 0.65rem 0.85rem;
    font-size: 0.85rem;
    font-weight: 600;
  }

  .section h2 {
    font-family: var(--font-heading);
    font-weight: 600;
    font-size: 0.95rem;
    margin: 0 0 0.6rem;
  }

  .meta-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 1rem;
    font-size: 0.85rem;
    color: var(--color-muted-fg);
    margin-bottom: 0.4rem;
  }

  .company-name {
    font-family: var(--font-heading);
    font-weight: 600;
    font-size: 1.05rem;
    margin: 0 0 0.4rem;
  }

  .badge {
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 600;
    background: var(--color-muted-fg);
    color: var(--color-surface);
  }

  .badge.active { background: var(--color-accent); }

  .report-text { font-size: 0.9rem; }
  .report-text h1, .report-text h2, .report-text h3 {
    font-family: var(--font-heading);
    font-weight: 600;
    margin: 0.9rem 0 0.4rem;
  }
  .report-text h1:first-child, .report-text h2:first-child,
  .report-text h3:first-child { margin-top: 0; }
  .report-text p { margin: 0 0 0.6rem; }
  .report-text ul, .report-text ol { margin: 0 0 0.6rem; padding-left: 1.3rem; }
  .report-text li { margin-bottom: 0.2rem; }
  .report-text strong { font-weight: 700; }
  .report-text hr { border: none; border-top: 1px solid var(--color-border); margin: 0.9rem 0; }
  .report-text table {
    border-collapse: collapse;
    width: 100%;
    display: block;
    overflow-x: auto;
    margin: 0 0 0.6rem;
    font-size: 0.85rem;
  }
  .report-text th, .report-text td {
    border: 1px solid var(--color-border);
    padding: 0.35rem 0.5rem;
    text-align: left;
  }
  .report-text th { background: var(--color-background); font-weight: 600; }

  ul.sources {
    list-style: none; padding: 0; margin: 0;
    display: flex; flex-direction: column; gap: 0.4rem;
  }
  ul.sources li {
    border: 1px solid var(--color-border); border-radius: 8px; padding: 0.5rem 0.65rem;
  }
  ul.sources a {
    color: var(--color-secondary); text-decoration: none; font-size: 0.85rem;
    word-break: break-all;
  }
  ul.sources a:hover { text-decoration: underline; }

  .empty { color: var(--color-muted-fg); font-style: italic; font-size: 0.85rem; }

  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-bottom: 0.75rem;
  }

  .tab-btn {
    font-family: var(--font-heading);
    font-weight: 600;
    font-size: 0.8rem;
    padding: 0.4rem 0.75rem;
    border: 1px solid var(--color-border);
    border-radius: 8px;
    background: var(--color-surface);
    color: var(--color-muted-fg);
    cursor: pointer;
  }

  .tab-btn.active {
    background: var(--color-primary); color: #fff; border-color: var(--color-primary);
  }
  .tab-btn:focus-visible { outline: 2px solid var(--color-ring); outline-offset: 2px; }

  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  .priority-list {
    list-style: none; padding: 0; margin: 0.6rem 0 0;
    display: flex; flex-direction: column; gap: 0.5rem;
  }
  .priority-list li {
    border: 1px solid var(--color-border); border-radius: 8px;
    padding: 0.5rem 0.65rem; font-size: 0.85rem;
  }
  .priority-list .hint { display: block; margin-top: 0.25rem; }

  @media (prefers-reduced-motion: reduce) {
    button { transition: none; }
  }
</style>
</head>
<body>
<h1>Справка за българска фирма</h1>
<p class="subtitle">Официални регистърни данни + уеб проверка, обединени в един доклад.</p>

<form id="lookup-form" class="card">
  <div class="field">
    <label for="q">ЕИК или име на фирма</label>
    <input type="text" id="q" name="q" required autocomplete="off">
  </div>
  <div class="field">
    <label for="token">Токен за достъп</label>
    <input type="password" id="token" name="token" autocomplete="off">
    <div class="hint">Пази се локално в браузъра ти, не се праща никъде другаде.</div>
  </div>
  <button type="submit" id="submit-btn">Провери фирма</button>
</form>

<div id="status" role="status" aria-live="polite"></div>
<div id="result"></div>

<script src="https://cdn.jsdelivr.net/npm/marked@18.0.9/lib/marked.umd.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.4.13/dist/purify.min.js"></script>
<script>
DOMPurify.addHook('afterSanitizeAttributes', function (node) {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

function renderMarkdown(text) {
  return DOMPurify.sanitize(marked.parse(text || ''));
}

const form = document.getElementById('lookup-form');
const qInput = document.getElementById('q');
const tokenInput = document.getElementById('token');
const submitBtn = document.getElementById('submit-btn');
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');

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

tokenInput.value = localStorage.getItem('bg_company_lookup_token') || '';

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function renderOfficialData(data) {
  if (!data) {
    return '<p class="empty">Фирмата не е намерена в официалния регистър.</p>';
  }
  const managers = (data.managers || []).map(m => escapeHtml(m.name || '?')).join(', ') || '—';
  const status = data.status || '—';
  const badgeClass = /акт|active/i.test(String(status)) ? 'badge active' : 'badge';
  return `
    <p class="company-name">${escapeHtml(data.name || '(без име)')}</p>
    <div class="meta-row">
      <span>ЕИК: ${escapeHtml(data.uic)}</span>
      <span class="${badgeClass}">${escapeHtml(status)}</span>
    </div>
    <div class="meta-row">
      <span>Управители: ${managers}</span>
    </div>
  `;
}

function renderSources(sources) {
  if (!sources || sources.length === 0) {
    return '<p class="empty">Няма източници.</p>';
  }
  return '<ul class="sources">' + sources.map(s => {
    const label = escapeHtml(s.title || s.url);
    const href = escapeHtml(s.url);
    return `<li><a href="${href}" target="_blank" rel="noopener">${label}</a></li>`;
  }).join('') + '</ul>';
}

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

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = qInput.value.trim();
  const token = tokenInput.value.trim();
  localStorage.setItem('bg_company_lookup_token', token);

  submitBtn.disabled = true;
  submitBtn.textContent = 'Зареждане...';
  statusEl.innerHTML = 'Зареждане... (може да отнеме до минута)';
  resultEl.innerHTML = '';

  try {
    const url = '/api/report?q=' + encodeURIComponent(q) + '&token=' + encodeURIComponent(token);
    const resp = await fetch(url);

    let body;
    try {
      body = await resp.json();
    } catch {
      statusEl.innerHTML = '<div class="error-box" role="alert">Сървърът отговори бавно ' +
        'или невалидно (вероятно timeout) — опитай пак след малко.</div>';
      return;
    }

    if (!resp.ok) {
      const msg = escapeHtml(body.error || 'неизвестна грешка');
      statusEl.innerHTML = '<div class="error-box" role="alert">Грешка (' + resp.status +
        '): ' + msg + '</div>';
      return;
    }

    statusEl.innerHTML = '';
    resultEl.innerHTML = `
      <div class="tabs" role="tablist">
        <button type="button" class="tab-btn active" data-tab="official"
          role="tab" aria-selected="true">Официални данни</button>
        <button type="button" class="tab-btn" data-tab="report"
          role="tab" aria-selected="false">Обединен доклад</button>
        <button type="button" class="tab-btn" data-tab="sources"
          role="tab" aria-selected="false">Уеб източници</button>
        <button type="button" class="tab-btn" data-tab="priority"
          role="tab" aria-selected="false">Оценка на зелени технологии</button>
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
          <h2>Оценка на зелени технологии</h2>
          ${renderPriorityAssessment(body.priority_assessment)}
        </div>
      </div>
    `;
  } catch (err) {
    statusEl.innerHTML = '<div class="error-box" role="alert">Грешка при връзка със сървъра: ' +
      escapeHtml(err.message) + '</div>';
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Провери фирма';
  }
});
</script>
</body>
</html>"""


def create_app(
    access_token: str | None = None,
    report_cache_ttl_seconds: float = REPORT_CACHE_TTL_SECONDS,
) -> Flask:
    app = Flask(__name__)
    app.config["ACCESS_TOKEN"] = access_token
    report_cache = TTLCache(ttl_seconds=report_cache_ttl_seconds)

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

        cache_key = q.strip().lower()
        cached = report_cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)

        # lookup() (companybook.bg) и research() (Gemini) не зависят един от друг —
        # изпълняват се успоредно, за да срежем общото latency (важно за да не удряме
        # Render-ия gateway timeout, тъй като cross_check() после добавя още едно
        # последователно Gemini извикване).
        official_data = None
        research_result = None
        early_response = None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            lookup_future = executor.submit(lookup, q)
            research_future = executor.submit(research.research, q)

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

        if early_response:
            return early_response

        priority_assessment = priority.evaluate(official_data) if official_data else None

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
            "priority_assessment": priority_assessment,
        }
        report_cache.set(cache_key, result)
        return jsonify(result)

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
