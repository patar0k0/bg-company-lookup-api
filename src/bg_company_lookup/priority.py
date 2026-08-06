"""
Проверка на фирмени данни (изхода на core.lookup()) срещу приоритетните критерии
на конкретна грантова схема: община на изпълнение, икономическа дейност (КИД-2008)
и област на седалище. Чисти функции, без мрежови извиквания.
"""

from __future__ import annotations

PRIORITY_MUNICIPALITIES: frozenset[str] = frozenset(
    {
        "Враца",
        "Ловеч",
        "Лом",
        "Видин",
        "Монтана",
        "Силистра",
        "Горна Оряховица",
        "Севлиево",
        "Габрово",
        "Свищов",
        "Търговище",
        "Добрич",
        "Шумен",
        "Аксаково",
        "Кюстендил",
        "Петрич",
        "Сандански",
        "Перник",
        "Дупница",
        "Гоце Делчев",
        "Гърмен",
        "Сатовча",
        "Самоков",
        "Ботевград",
        "Благоевград",
        "Сливен",
        "Казанлък",
        "Карнобат",
        "Ямбол",
        "Велинград",
        "Смолян",
        "Пазарджик",
        "Карлово",
        "Хасково",
        "Пловдив",
        "Свиленград",
        "Панагюрище",
        "Пещера",
        "Кърджали",
        "Ардино",
        "Джебел",
        "Черноочене",
        "Димитровград",
    }
)

PRIORITY_DISTRICTS: frozenset[str] = frozenset(
    {
        "Хасково",
        "Силистра",
        "Сливен",
        "Кюстендил",
        "Видин",
        "Монтана",
        "Кърджали",
        "Перник",
        "Пазарджик",
        "Благоевград",
        "Смолян",
        "Добрич",
        "Разград",
        "Шумен",
        "Плевен",
        "Ямбол",
        "Ловеч",
    }
)

# Приоритетни КИД-2008 (NACE Rev.2 BG) раздели — 2-цифрен код -> описание.
# Мапнати от свободния текст на критериите към реални класове на разделите.
PRIORITY_NACE_DIVISIONS: dict[str, str] = {
    "20": "Производство на химични продукти",
    "21": "Производство на лекарствени вещества и продукти",
    "26": "Производство на компютърна и комуникационна техника, електронни и оптични продукти",
    "27": "Производство на електрически съоръжения",
    "28": "Производство на машини и оборудване, с общо и специално предназначение",
    "29": "Производство на автомобили, ремаркета и полуремаркета",
    "30": "Производство на превозни средства, без автомобили",
    "32": "Други разнообразни производства, некласифицирани другаде",
    "33": (
        "Ремонт и поддържане на бойни бронирани транспортни машини, военни "
        "плавателни съдове, въздухоплавателни и космически средства"
    ),
    "59": "Производство на филми и телевизионни предавания, звукозаписване и издаване на музика",
    "60": (
        "Радио- и телевизионна дейност, информационни агенции и разпространение на друго съдържание"
    ),
    "61": "Телекомуникации",
    "62": "Дейности в областта на информационните технологии",
    "63": (
        "Инфраструктура за информационни технологии, обработка на данни, хостинг и други "
        "информационни услуги"
    ),
    "71": "Архитектурни и инженерни дейности; технически изпитвания и анализи",
    "72": "Научноизследователска и развойна дейност",
}

INVESTMENT_LOCATION_NOTE = (
    "Реализацията на инвестицията в тази област изисква ръчна проверка — "
    "официалният регистър не съдържа информация за мястото на изпълнение на проекта."
)


def _normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def evaluate(company_data: dict) -> dict:
    """
    Чиста функция — без мрежови извиквания. Приема речник във формата на
    core.lookup()'s изход и връща оценка по 3-те приоритетни критерия.
    """
    address = company_data.get("address") or {}
    activity = company_data.get("activity") or {}
    nkids = activity.get("nkids") or []

    municipality_value = address.get("municipality")
    municipality_matched = _normalize(municipality_value) in {
        _normalize(m) for m in PRIORITY_MUNICIPALITIES
    }

    company_nkids = [{"code": n.get("code"), "description": n.get("description")} for n in nkids]

    matched_divisions = []
    seen_divisions = set()
    for n in nkids:
        division = (n.get("code") or "")[:2]
        if division in PRIORITY_NACE_DIVISIONS and division not in seen_divisions:
            seen_divisions.add(division)
            matched_divisions.append(
                {"code": division, "description": PRIORITY_NACE_DIVISIONS[division]}
            )

    district_value = address.get("district")
    district_matched = _normalize(district_value) in {_normalize(d) for d in PRIORITY_DISTRICTS}

    auto_matched_count = int(municipality_matched) + int(bool(matched_divisions))

    return {
        "municipality": {
            "matched": municipality_matched,
            "value": municipality_value,
        },
        "activity": {
            "matched": bool(matched_divisions),
            "matched_divisions": matched_divisions,
            "company_nkids": company_nkids,
        },
        "district": {
            "matched": district_matched,
            "value": district_value,
            "investment_location_note": INVESTMENT_LOCATION_NOTE,
        },
        "auto_matched_count": auto_matched_count,
        "total_criteria": 3,
    }
