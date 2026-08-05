"""
Малка обвивка около Gemini API (google-genai SDK) за:
  - research(query)          — уеб търсене с Google Search grounding, обобщено
                                на български, с цитирани източници.
  - cross_check(query, ...)  — кръстосана проверка на официални регистърни данни
                                срещу уеб резултати.

Безплатен tier (2026): Flash/Flash-Lite моделите поддържат Google Search grounding
безплатно (5000 grounded заявки/месец), без нужда от карта — API ключ се взима от
https://aistudio.google.com/apikey
"""

from __future__ import annotations

import json
import os

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-flash-lite-latest"

CROSS_CHECK_PROMPT_TEMPLATE = """Официални регистърни данни: {company_json}
Резултати от уеб търсене: {research_answer}

Сравни ги. Ако уеб резултатите твърдят нещо (напр. оборот, брой служители, финансово \
състояние), което НЕ се потвърждава от официалните данни — отбележи го изрично като \
непотвърдено, не го представяй като факт. Дай един обединен доклад на български, \
разграничавайки ясно 'потвърдено от регистъра' от 'според уеб източници, непотвърдено'."""


class ResearchServiceError(Exception):
    """Gemini API недостъпен/грешка при извикване (аналог на LookupServiceError)."""


def _client(api_key: str | None) -> genai.Client:
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Липсва API ключ. Подай го като аргумент или сложи GEMINI_API_KEY в env."
        )
    return genai.Client(api_key=api_key)


def _model_name(model: str | None) -> str:
    return model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


def _extract_sources(response) -> list[dict]:
    sources = []
    for candidate in getattr(response, "candidates", None) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        chunks = getattr(metadata, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            uri = getattr(web, "uri", None)
            if not uri:
                continue
            sources.append({"title": getattr(web, "title", None), "url": uri})
    return sources


def research(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    """
    Уеб търсене през Gemini (Google Search grounding) по зададена тема.

    Връща: {"query": ..., "answer": ..., "sources": [{"title": ..., "url": ...}, ...]}

    Хвърля:
        RuntimeError         — липсва GEMINI_API_KEY
        ResearchServiceError — Gemini API недостъпен/грешка при извикване
    """
    client = _client(api_key)
    prompt = (
        "Обобщи резултатите от търсене по следната тема на български език, "
        "структурирано (с подходящи секции/точки), и цитирай източниците в края:\n\n"
        f"{query}"
    )
    try:
        response = client.models.generate_content(
            model=_model_name(model),
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
    except Exception as e:
        raise ResearchServiceError(f"Gemini API недостъпен: {e}") from e

    return {
        "query": query,
        "answer": response.text,
        "sources": _extract_sources(response),
    }


def cross_check(
    query: str,
    official_data: dict | None,
    research_answer: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    _client(api_key)
    raise NotImplementedError
