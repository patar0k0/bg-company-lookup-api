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
