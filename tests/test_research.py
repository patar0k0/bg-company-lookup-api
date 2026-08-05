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


@patch("bg_company_lookup.research.genai.Client")
def test_research_returns_answer_and_sources(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response()

    result = research("тестова тема", api_key="fake-key")

    assert result["query"] == "тестова тема"
    assert result["answer"] == "обобщение"
    assert result["sources"] == [{"title": "Пример Източник", "url": "https://example.bg/article"}]


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
