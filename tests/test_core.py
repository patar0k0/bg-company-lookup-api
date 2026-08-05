from unittest.mock import MagicMock, patch

import pytest
import requests

from bg_company_lookup.core import (
    CompanyNotFound,
    LookupServiceError,
    _looks_like_eik,
    format_profile,
    lookup,
)


class TestLooksLikeEik:
    def test_plain_nine_digit_eik(self):
        assert _looks_like_eik("106590295") is True

    def test_bg_prefixed_vat_number(self):
        assert _looks_like_eik("BG106590295") is True

    def test_company_name_is_not_eik(self):
        assert _looks_like_eik("Декорамет ЕООД") is False


class TestLookup:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("COMPANYBOOK_API_KEY", raising=False)
        with pytest.raises(RuntimeError):
            lookup("106590295", api_key=None)

    @patch("bg_company_lookup.core.requests.get")
    def test_lookup_by_eik_returns_profile(self, mock_get):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "company": {"uic": "106590295", "companyName": {"name": "ДЕКОРАМЕТ"}}
        }
        response.raise_for_status = lambda: None
        mock_get.return_value = response

        profile = lookup("106590295", api_key="fake-key", include_financial=False)

        assert profile["uic"] == "106590295"
        assert profile["name"] == "ДЕКОРАМЕТ"
        mock_get.assert_called_once()

    @patch("bg_company_lookup.core.requests.get")
    def test_lookup_raises_company_not_found_on_404(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)

        with pytest.raises(CompanyNotFound):
            lookup("999999999", api_key="fake-key", include_financial=False)

    @patch("bg_company_lookup.core.requests.get")
    def test_lookup_by_name_resolves_eik_via_search(self, mock_get):
        search_resp = MagicMock(status_code=200)
        search_resp.json.return_value = {"results": [{"uic": "106590295", "name": "ДЕКОРАМЕТ"}]}
        search_resp.raise_for_status = lambda: None

        detail_resp = MagicMock(status_code=200)
        detail_resp.json.return_value = {
            "company": {"uic": "106590295", "companyName": {"name": "ДЕКОРАМЕТ"}}
        }
        detail_resp.raise_for_status = lambda: None

        mock_get.side_effect = [search_resp, detail_resp]

        profile = lookup("Декорамет ЕООД", api_key="fake-key", include_financial=False)

        assert profile["uic"] == "106590295"
        assert mock_get.call_count == 2

    @patch("bg_company_lookup.core.requests.get")
    def test_lookup_raises_company_not_found_when_search_empty(self, mock_get):
        search_resp = MagicMock(status_code=200)
        search_resp.json.return_value = {"results": []}
        search_resp.raise_for_status = lambda: None
        mock_get.return_value = search_resp

        with pytest.raises(CompanyNotFound):
            lookup("Несъществуваща Фирма ООД", api_key="fake-key")

    @patch("bg_company_lookup.core.requests.get")
    def test_lookup_wraps_connection_error_as_lookup_service_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with pytest.raises(LookupServiceError):
            lookup("106590295", api_key="fake-key", include_financial=False)

    @patch("bg_company_lookup.core._financial")
    @patch("bg_company_lookup.core.requests.get")
    def test_lookup_succeeds_even_if_financial_fetch_fails(self, mock_get, mock_financial):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "company": {"uic": "106590295", "companyName": {"name": "ДЕКОРАМЕТ"}}
        }
        response.raise_for_status = lambda: None
        mock_get.return_value = response
        mock_financial.return_value = None

        profile = lookup("106590295", api_key="fake-key", include_financial=True)

        assert profile["financial"] is None


class TestFormatProfile:
    def test_handles_minimal_profile_without_crashing(self):
        text = format_profile({"uic": "1", "name": "X"})
        assert "X" in text
