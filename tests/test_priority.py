from bg_company_lookup.priority import evaluate


def _company(municipality=None, district=None, nkids=None):
    return {
        "address": {"municipality": municipality, "district": district},
        "activity": {"subject": "...", "nkids": nkids or []},
    }


def test_municipality_match():
    company = _company(municipality="Враца")
    result = evaluate(company)
    assert result["municipality"]["matched"] is True
    assert result["municipality"]["value"] == "Враца"


def test_municipality_no_match():
    company = _company(municipality="София")
    result = evaluate(company)
    assert result["municipality"]["matched"] is False


def test_municipality_match_is_case_and_whitespace_insensitive():
    company = _company(municipality="  враца  ")
    result = evaluate(company)
    assert result["municipality"]["matched"] is True


def test_activity_matches_priority_nace_division():
    company = _company(nkids=[{"code": "2110", "description": "Производство на лекарства"}])
    result = evaluate(company)
    assert result["activity"]["matched"] is True
    assert result["activity"]["matched_divisions"] == [
        {"code": "21", "description": "Производство на лекарствени вещества и продукти"}
    ]
    assert result["activity"]["company_nkids"] == [
        {"code": "2110", "description": "Производство на лекарства"}
    ]


def test_activity_no_match():
    company = _company(nkids=[{"code": "4525", "description": "Строителни дейности"}])
    result = evaluate(company)
    assert result["activity"]["matched"] is False
    assert result["activity"]["matched_divisions"] == []


def test_activity_matches_when_any_of_multiple_nkids_matches():
    company = _company(
        nkids=[
            {"code": "4525", "description": "Строителни дейности"},
            {"code": "6201", "description": "Компютърно програмиране"},
        ]
    )
    result = evaluate(company)
    assert result["activity"]["matched"] is True
    assert result["activity"]["matched_divisions"] == [
        {"code": "62", "description": "Дейности в областта на информационните технологии"}
    ]


def test_district_match():
    company = _company(district="Хасково")
    result = evaluate(company)
    assert result["district"]["matched"] is True
    assert "изисква ръчна проверка" in result["district"]["investment_location_note"]


def test_district_no_match():
    company = _company(district="Варна")
    result = evaluate(company)
    assert result["district"]["matched"] is False
    assert "изисква ръчна проверка" in result["district"]["investment_location_note"]


def test_auto_matched_count_counts_municipality_and_activity_only():
    company = _company(
        municipality="Враца",
        district="Варна",
        nkids=[{"code": "2110", "description": "..."}],
    )
    result = evaluate(company)
    assert result["auto_matched_count"] == 2
    assert result["total_criteria"] == 3


def test_evaluate_handles_missing_address_and_activity():
    result = evaluate({})
    assert result["municipality"]["matched"] is False
    assert result["activity"]["matched"] is False
    assert result["district"]["matched"] is False
    assert result["auto_matched_count"] == 0
