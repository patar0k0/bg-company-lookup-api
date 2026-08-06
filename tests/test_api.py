from unittest.mock import patch

import pytest

from bg_company_lookup.api import create_app
from bg_company_lookup.core import CompanyNotFound, LookupServiceError
from bg_company_lookup.research import ResearchServiceError


@pytest.fixture
def client():
    app = create_app(access_token=None)
    app.testing = True
    return app.test_client()


@pytest.fixture
def protected_client():
    app = create_app(access_token="secret-token")
    app.testing = True
    return app.test_client()


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


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


def test_company_requires_q_param(client):
    resp = client.get("/api/company")
    assert resp.status_code == 400


def test_company_rejects_overlong_query(client):
    resp = client.get("/api/company", query_string={"q": "x" * 300})
    assert resp.status_code == 400


def test_company_rejects_blank_query(client):
    resp = client.get("/api/company", query_string={"q": "   "})
    assert resp.status_code == 400


def test_company_rejects_missing_token_when_configured(protected_client):
    resp = protected_client.get("/api/company", query_string={"q": "106590295"})
    assert resp.status_code == 401


def test_company_accepts_correct_token(protected_client):
    with patch("bg_company_lookup.api.lookup") as mock_lookup:
        mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
        resp = protected_client.get(
            "/api/company", query_string={"q": "106590295", "token": "secret-token"}
        )
    assert resp.status_code == 200


@patch("bg_company_lookup.api.lookup")
def test_company_returns_profile_json(mock_lookup, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}

    resp = client.get("/api/company", query_string={"q": "106590295"})

    assert resp.status_code == 200
    assert resp.get_json()["uic"] == "106590295"


@patch("bg_company_lookup.api.lookup")
def test_company_returns_404_when_not_found(mock_lookup, client):
    mock_lookup.side_effect = CompanyNotFound("не е намерена")

    resp = client.get("/api/company", query_string={"q": "000000000"})

    assert resp.status_code == 404


@patch("bg_company_lookup.api.lookup")
def test_company_returns_500_on_missing_api_key(mock_lookup, client):
    mock_lookup.side_effect = RuntimeError("Липсва API ключ")

    resp = client.get("/api/company", query_string={"q": "106590295"})

    assert resp.status_code == 500


@patch("bg_company_lookup.api.lookup")
def test_company_returns_502_when_upstream_unavailable(mock_lookup, client):
    mock_lookup.side_effect = LookupServiceError("companybook.bg недостъпен")

    resp = client.get("/api/company", query_string={"q": "106590295"})

    assert resp.status_code == 502


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


def test_report_requires_q_param(client):
    resp = client.get("/api/report")
    assert resp.status_code == 400


def test_report_rejects_missing_token_when_configured(protected_client):
    resp = protected_client.get("/api/report", query_string={"q": "106590295"})
    assert resp.status_code == 401


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


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_500_on_missing_companybook_key(mock_lookup, mock_research_module, client):
    mock_lookup.side_effect = RuntimeError("Липсва API ключ")
    # lookup() и research() се пускат успоредно (виж коментара в api.py), затова
    # research() СЕ извиква дори когато lookup() гръмне пръв — не проверяваме
    # тук, че не е извикан.

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 500


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_502_when_lookup_upstream_fails(mock_lookup, mock_research_module, client):
    mock_lookup.side_effect = LookupServiceError("companybook.bg недостъпен")

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 502


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_returns_502_when_research_fails(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
    mock_research_module.research.side_effect = ResearchServiceError("Gemini недостъпен")

    resp = client.get("/api/report", query_string={"q": "106590295"})

    assert resp.status_code == 502


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


@patch("bg_company_lookup.api.research")
@patch("bg_company_lookup.api.lookup")
def test_report_does_not_cache_error_responses(mock_lookup, mock_research_module, client):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}
    mock_research_module.research.side_effect = ResearchServiceError("Gemini недостъпен")

    first = client.get("/api/report", query_string={"q": "106590295"})
    second = client.get("/api/report", query_string={"q": "106590295"})

    assert first.status_code == 502
    assert second.status_code == 502
    assert mock_research_module.research.call_count == 2
