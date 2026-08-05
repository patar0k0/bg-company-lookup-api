from unittest.mock import patch

from bg_company_lookup.cli import main
from bg_company_lookup.core import CompanyNotFound


@patch("bg_company_lookup.cli.lookup")
def test_main_prints_formatted_profile_and_returns_zero(mock_lookup, capsys):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}

    exit_code = main(["106590295"])

    captured = capsys.readouterr()
    assert "ДЕКОРАМЕТ" in captured.out
    assert exit_code == 0


@patch("bg_company_lookup.cli.lookup")
def test_main_prints_json_with_flag(mock_lookup, capsys):
    mock_lookup.return_value = {"uic": "106590295", "name": "ДЕКОРАМЕТ"}

    exit_code = main(["106590295", "--json"])

    captured = capsys.readouterr()
    assert '"uic": "106590295"' in captured.out
    assert exit_code == 0


@patch("bg_company_lookup.cli.lookup")
def test_main_reports_error_and_nonzero_exit_on_not_found(mock_lookup, capsys):
    mock_lookup.side_effect = CompanyNotFound("не е намерена")

    exit_code = main(["000000000"])

    captured = capsys.readouterr()
    assert "не е намерена" in captured.err
    assert exit_code == 1
