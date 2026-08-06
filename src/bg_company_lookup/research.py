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
import re

from google import genai
from google.genai import errors, types

DEFAULT_MODEL = "gemini-3.5-flash-lite"

FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
)

NO_ANSWER_MESSAGE = "Не са намерени резултати от уеб търсенето по тази тема."

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


def _model_chain(model: str | None) -> list[str]:
    """Основният модел, последван от FALLBACK_MODELS (без дублиране)."""
    chain = [_model_name(model)]
    for candidate in FALLBACK_MODELS:
        if candidate not in chain:
            chain.append(candidate)
    return chain


def _generate_with_fallback(client: genai.Client, contents: str, config=None, model=None):
    """
    Пробва моделите от _model_chain() последователно. При 429 (изчерпана квота на
    конкретния модел) минава към следващия; при друга грешка спира веднага.
    """
    last_error: Exception | None = None
    for candidate_model in _model_chain(model):
        kwargs = {"model": candidate_model, "contents": contents}
        if config is not None:
            kwargs["config"] = config
        try:
            return client.models.generate_content(**kwargs)
        except errors.APIError as e:
            if e.code != 429:
                raise ResearchServiceError(f"Gemini API недостъпен: {e}") from e
            last_error = e
        except Exception as e:
            raise ResearchServiceError(f"Gemini API недостъпен: {e}") from e

    raise ResearchServiceError(
        f"Gemini API квота изчерпана за всички опитани модели: {last_error}"
    ) from last_error


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
    response = _generate_with_fallback(
        client,
        prompt,
        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        model=model,
    )

    return {
        "query": query,
        "answer": response.text or NO_ANSWER_MESSAGE,
        "sources": _extract_sources(response),
    }


def cross_check(
    query: str,
    official_data: dict | None,
    research_answer: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """
    Кръстосана проверка: праща официалните регистърни данни + уеб резултатите на
    Gemini и връща обединен доклад на български (текст), разграничаващ потвърдени
    от непотвърдени твърдения.

    Хвърля:
        RuntimeError         — липсва GEMINI_API_KEY
        ResearchServiceError — Gemini API недостъпен/грешка при извикване
    """
    client = _client(api_key)
    company_json = (
        json.dumps(official_data, ensure_ascii=False, indent=2)
        if official_data is not None
        else "(фирмата не е намерена в официалния регистър)"
    )
    prompt = CROSS_CHECK_PROMPT_TEMPLATE.format(
        company_json=company_json, research_answer=research_answer
    )
    response = _generate_with_fallback(client, prompt, model=model)

    return response.text


ADDRESSES_PROMPT_TEMPLATE = """Намери всички известни физически адреси на фирмата „{query}“ — \
офиси, обекти, магазини, складове, производствени бази — от сайта на фирмата, Google Maps, \
бизнес указатели, обяви и други източници.

Върни САМО чист JSON списък (без markdown форматиране, без обяснения преди или след), от обекти \
във формат:
[{{"address": "пълен адрес като текст", "context": "кратко описание откъде/какво е (или null)", \
"source_url": "URL на източника (или null)"}}]

Ако не намериш нищо конкретно, върни []."""


def _parse_addresses_json(text: str | None) -> list[dict]:
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    addresses = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get("address"):
            continue
        addresses.append(
            {
                "address": item.get("address"),
                "context": item.get("context"),
                "source_url": item.get("source_url"),
            }
        )
    return addresses


def find_addresses(query: str, api_key: str | None = None, model: str | None = None) -> dict:
    """
    Уеб търсене (Google Search grounding) за всички известни физически адреси на фирмата.

    Връща: {"query": ..., "addresses": [{"address": str, "context": str | None,
                                          "source_url": str | None}, ...]}

    При невалиден/непарсируем JSON отговор от модела връща addresses=[] (soft degrade) —
    само upstream грешки (липсващ ключ, недостъпен Gemini) се третират като изключения.

    Хвърля:
        RuntimeError         — липсва GEMINI_API_KEY
        ResearchServiceError — Gemini API недостъпен/грешка при извикване
    """
    client = _client(api_key)
    prompt = ADDRESSES_PROMPT_TEMPLATE.format(query=query)
    response = _generate_with_fallback(
        client,
        prompt,
        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        model=model,
    )

    return {"query": query, "addresses": _parse_addresses_json(response.text)}


def _normalize_address(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[.,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _registry_address_text(addr: dict | None) -> str | None:
    if not addr:
        return None
    parts = [
        addr.get("street"),
        addr.get("streetNumber"),
        addr.get("settlement"),
        addr.get("municipality"),
        addr.get("district"),
        addr.get("postCode"),
    ]
    text = ", ".join(p for p in parts if p)
    return text or None


def merge_addresses(official_data: dict | None, web_result: dict) -> list[dict]:
    """
    Обединява регистровите адреси (от official_data, резултат на core.lookup()) с намерените
    в уеб адреси (от find_addresses()) в един списък, всеки маркиран със source.

    Връща списък от:
      {"address": str, "source": "registry" | "web", "label": str | None,
       "context": str | None, "source_url": str | None, "differs_from_registry": bool | None}

    label е зададен само за registry записи. differs_from_registry е None за registry записи
    (не е приложимо) и bool за web записите — True, ако адресът не съвпада (дори частично,
    като подниз след нормализация) с нито един регистров адрес.
    """
    merged = []
    registry_texts = []

    if official_data:
        seat_text = _registry_address_text(official_data.get("address"))
        if seat_text:
            merged.append(
                {
                    "address": seat_text,
                    "source": "registry",
                    "label": "Адрес на управление",
                    "context": None,
                    "source_url": None,
                    "differs_from_registry": None,
                }
            )
            registry_texts.append(_normalize_address(seat_text))

        corr_text = _registry_address_text(official_data.get("correspondence_address"))
        if corr_text and _normalize_address(corr_text) not in registry_texts:
            merged.append(
                {
                    "address": corr_text,
                    "source": "registry",
                    "label": "Адрес за кореспонденция",
                    "context": None,
                    "source_url": None,
                    "differs_from_registry": None,
                }
            )
            registry_texts.append(_normalize_address(corr_text))

    for item in (web_result or {}).get("addresses", []):
        web_text = item.get("address")
        if not web_text:
            continue
        normalized_web = _normalize_address(web_text)
        differs = not any(
            normalized_web in reg or reg in normalized_web for reg in registry_texts
        )
        merged.append(
            {
                "address": web_text,
                "source": "web",
                "label": None,
                "context": item.get("context"),
                "source_url": item.get("source_url"),
                "differs_from_registry": differs,
            }
        )

    return merged
