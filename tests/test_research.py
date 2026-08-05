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
