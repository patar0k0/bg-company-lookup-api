from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors

from bg_company_lookup.research import (
    ResearchServiceError,
    cross_check,
    find_addresses,
    merge_addresses,
    research,
)


def _rate_limit_error():
    return errors.ClientError(
        429,
        {"error": {"code": 429, "message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}},
    )


def _bad_request_error():
    return errors.ClientError(
        400,
        {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}},
    )


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
def test_research_returns_placeholder_when_gemini_returns_no_text(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text=None, with_sources=False
    )

    result = research("тестова тема", api_key="fake-key")

    assert result["answer"] == "Не са намерени резултати от уеб търсенето по тази тема."


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


def test_find_addresses_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        find_addresses("Декорамет ЕООД", api_key=None)


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_returns_parsed_list(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='[{"address": "гр. София, ул. Тест 1", "context": "офис", '
        '"source_url": "https://example.bg"}]',
        with_sources=False,
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["query"] == "Декорамет ЕООД"
    assert result["addresses"] == [
        {
            "address": "гр. София, ул. Тест 1",
            "context": "офис",
            "source_url": "https://example.bg",
        }
    ]


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_strips_markdown_code_fence(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='```json\n[{"address": "гр. Пловдив, бул. Тест 5"}]\n```',
        with_sources=False,
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == [
        {"address": "гр. Пловдив, бул. Тест 5", "context": None, "source_url": None}
    ]


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_returns_empty_list_on_invalid_json(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text="За съжаление не намерих нищо конкретно.", with_sources=False
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == []


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_returns_empty_list_when_top_level_not_a_list(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='{"address": "гр. София"}', with_sources=False
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == []


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_skips_items_without_address_field(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.return_value = _mock_response(
        text='[{"context": "няма адрес поле"}, "не е обект", '
        '{"address": "гр. Варна, ул. Валидна 2"}]',
        with_sources=False,
    )

    result = find_addresses("Декорамет ЕООД", api_key="fake-key")

    assert result["addresses"] == [
        {"address": "гр. Варна, ул. Валидна 2", "context": None, "source_url": None}
    ]


@patch("bg_company_lookup.research.genai.Client")
def test_find_addresses_raises_service_error_on_sdk_failure(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.side_effect = RuntimeError("boom")

    with pytest.raises(ResearchServiceError):
        find_addresses("Декорамет ЕООД", api_key="fake-key")


def test_merge_addresses_lists_seat_and_correspondence_when_different():
    official_data = {
        "address": {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"},
        "correspondence_address": {
            "street": "ул. Втора",
            "streetNumber": "2",
            "settlement": "Пловдив",
        },
    }

    result = merge_addresses(official_data, {"addresses": []})

    assert result == [
        {
            "address": "ул. Първа, 1, София",
            "source": "registry",
            "label": "Адрес на управление",
            "context": None,
            "source_url": None,
            "differs_from_registry": None,
        },
        {
            "address": "ул. Втора, 2, Пловдив",
            "source": "registry",
            "label": "Адрес за кореспонденция",
            "context": None,
            "source_url": None,
            "differs_from_registry": None,
        },
    ]


def test_merge_addresses_skips_duplicate_correspondence_address():
    same_address = {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"}
    official_data = {"address": same_address, "correspondence_address": dict(same_address)}

    result = merge_addresses(official_data, {"addresses": []})

    assert len(result) == 1
    assert result[0]["label"] == "Адрес на управление"


def test_merge_addresses_all_web_addresses_differ_when_no_official_data():
    web_result = {
        "addresses": [{"address": "гр. Варна, ул. Уеб 1", "context": None, "source_url": None}]
    }

    result = merge_addresses(None, web_result)

    assert result == [
        {
            "address": "гр. Варна, ул. Уеб 1",
            "source": "web",
            "label": None,
            "context": None,
            "source_url": None,
            "differs_from_registry": True,
        }
    ]


def test_merge_addresses_flags_web_address_matching_registry_as_not_differing():
    official_data = {"address": {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"}}
    web_result = {
        "addresses": [
            {
                "address": "ул. Първа 1, София, България",
                "context": "сайт",
                "source_url": "https://x.bg",
            }
        ]
    }

    result = merge_addresses(official_data, web_result)

    web_entry = next(a for a in result if a["source"] == "web")
    assert web_entry["differs_from_registry"] is False


def test_merge_addresses_flags_web_address_differing_from_registry():
    official_data = {"address": {"street": "ул. Първа", "streetNumber": "1", "settlement": "София"}}
    web_result = {
        "addresses": [
            {
                "address": "гр. Бургас, ул. Съвсем Друга 9",
                "context": "офис",
                "source_url": "https://x.bg",
            }
        ]
    }

    result = merge_addresses(official_data, web_result)

    web_entry = next(a for a in result if a["source"] == "web")
    assert web_entry["differs_from_registry"] is True


def test_merge_addresses_skips_web_items_without_address_text():
    result = merge_addresses(
        None, {"addresses": [{"address": "", "context": None, "source_url": None}]}
    )

    assert result == []


@patch("bg_company_lookup.research.genai.Client")
def test_research_falls_back_to_next_model_on_429(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.side_effect = [
        _rate_limit_error(),
        _mock_response(with_sources=False),
    ]

    result = research("тестова тема", api_key="fake-key")

    assert result["answer"] == "обобщение"
    calls = mock_client_cls.return_value.models.generate_content.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["model"] != calls[1].kwargs["model"]


@patch("bg_company_lookup.research.genai.Client")
def test_research_raises_after_all_models_exhausted(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.side_effect = _rate_limit_error()

    with pytest.raises(ResearchServiceError):
        research("тестова тема", api_key="fake-key")

    calls = mock_client_cls.return_value.models.generate_content.call_args_list
    # default model is already the first FALLBACK_MODELS entry, so it dedupes to 3 unique models
    assert len(calls) == 3


@patch("bg_company_lookup.research.genai.Client")
def test_research_does_not_fall_back_on_non_429_api_error(mock_client_cls):
    mock_client_cls.return_value.models.generate_content.side_effect = _bad_request_error()

    with pytest.raises(ResearchServiceError):
        research("тестова тема", api_key="fake-key")

    calls = mock_client_cls.return_value.models.generate_content.call_args_list
    assert len(calls) == 1
