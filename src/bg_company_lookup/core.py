"""
BG Company Lookup — wrapper around the TheCompanyBook API (companybook.bg)

Дава ти ЕДНА функция: lookup(name_or_eik) -> dict с готов, структуриран профил
на българска фирма (ЕИК, адрес, управители, съдружници, капитал, ДДС,
контакти, дейност, и финансови данни ако имаш абонамент/лимит за тях).

Лимити на безплатния план: 100 общи заявки/ден, 30 заявки/ден за финансови
данни. Пълните данни на последната отчетна година са заключени без активен
абонамент.
"""

from __future__ import annotations

import os
import re

import requests

BASE_URL = "https://api.companybook.bg"


class CompanyNotFound(Exception):
    pass


class LookupServiceError(Exception):
    """companybook.bg е недостъпен/не отговаря коректно (мрежова грешка и др.)."""


def _headers(api_key: str) -> dict:
    return {"X-API-Key": api_key}


def _looks_like_eik(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    normalized = value.strip().upper().replace("BG", "")
    return digits.isdigit() and len(digits) in (9, 13) and digits == normalized


def _resolve_eik(name: str, api_key: str) -> tuple[str, list]:
    """Намира ЕИК по име чрез search endpoint-а (връща най-добрия match)."""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v2/companies/search",
            params={"name": name, "limit": 5},
            headers=_headers(api_key),
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise LookupServiceError(f"companybook.bg недостъпен при търсене по име: {e}") from e

    results = resp.json().get("results", [])
    if not results:
        raise CompanyNotFound(f"Няма намерена фирма с име: {name}")
    return results[0]["uic"], results


def _financial(uic: str, api_key: str) -> dict | None:
    try:
        resp = requests.get(
            f"{BASE_URL}/api/companies/{uic}/financial",
            headers=_headers(api_key),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def lookup(name_or_eik: str, api_key: str | None = None, include_financial: bool = True) -> dict:
    """
    Единствената функция, която ти трябва.

    name_or_eik: ЕИК (9 или 13 цифри) ИЛИ име на фирма (напр. "Декорамет ЕООД")
    api_key:     ако не подадеш, взима се от env variable COMPANYBOOK_API_KEY
    include_financial: дали да тегли и финансовите данни (отделна заявка, отделен дневен лимит)

    Хвърля:
        RuntimeError        — липсва API ключ
        CompanyNotFound      — няма такава фирма
        LookupServiceError   — companybook.bg недостъпен/мрежова грешка
    """
    api_key = api_key or os.environ.get("COMPANYBOOK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Липсва API ключ. Подай го като аргумент или сложи COMPANYBOOK_API_KEY в env."
        )

    alternative_matches = []
    value = name_or_eik.strip()

    if _looks_like_eik(value):
        uic = re.sub(r"\D", "", value)
    else:
        uic, results = _resolve_eik(value, api_key)
        alternative_matches = results[1:]

    try:
        resp = requests.get(
            f"{BASE_URL}/api/companies/{uic}",
            params={"with_data": "true"},
            headers=_headers(api_key),
            timeout=15,
        )
    except requests.RequestException as e:
        raise LookupServiceError(f"companybook.bg недостъпен: {e}") from e

    if resp.status_code == 404:
        raise CompanyNotFound(f"Няма фирма с ЕИК: {uic}")
    resp.raise_for_status()
    data = resp.json()
    company = data.get("company", {})

    profile = {
        "uic": company.get("uic"),
        "name": company.get("companyName", {}).get("name"),
        "legal_form": company.get("legalForm"),
        "status": company.get("status"),
        "address": company.get("seat"),
        "correspondence_address": company.get("correspondenceSeat"),
        "contacts": company.get("contacts"),
        "activity": {
            "subject": company.get("subjectOfActivity"),
            "nkids": company.get("nkids"),
        },
        "managers": company.get("managers"),
        "representatives": company.get("representatives"),
        "board_of_directors": company.get("boardOfDirectors"),
        "partners": company.get("partners"),
        "capital": company.get("capital"),
        "vat": company.get("registerInfo"),
        "subsidiaries": data.get("daughters"),
        "history": data.get("history"),
        "last_updated": company.get("lastUpdated"),
        "financial": None,
        "alternative_matches": alternative_matches,
    }

    if include_financial:
        profile["financial"] = _financial(uic, api_key)

    return profile


def _fmt_addr(addr: dict | None) -> str:
    if not addr:
        return "—"
    parts = [
        addr.get("street"),
        addr.get("streetNumber"),
        addr.get("settlement"),
        addr.get("municipality"),
        addr.get("district"),
        addr.get("postCode"),
    ]
    return ", ".join(p for p in parts if p) or "—"


def _fmt_people(people: list | None, role_label: str) -> str:
    if not people:
        return "—"
    lines = []
    for p in people:
        name = p.get("name", "?")
        share = p.get("contribution") or p.get("share")
        extra = f" ({share})" if share else ""
        lines.append(f"  - {name}{extra}")
    return "\n".join(lines)


def _fmt_money(amount, currency="BGN") -> str:
    if amount is None:
        return "—"
    try:
        return f"{float(amount):,.2f} {currency}".replace(",", " ")
    except (TypeError, ValueError):
        return f"{amount} {currency}"


def format_profile(profile: dict) -> str:
    """Превръща dict-а от lookup() в четим текстов профил (на български)."""
    lines = []
    lines.append(f"=== {profile.get('name', '(без име)')} ===")
    lines.append(
        f"ЕИК: {profile.get('uic', '—')}   "
        f"Правна форма: {profile.get('legal_form', '—')}   "
        f"Статус: {profile.get('status', '—')}"
    )
    lines.append("")

    lines.append("-- Адрес --")
    lines.append(_fmt_addr(profile.get("address")))
    lines.append("")

    contacts = profile.get("contacts") or {}
    if any(contacts.values()):
        lines.append("-- Контакти --")
        if contacts.get("phone"):
            lines.append(f"Телефон: {contacts['phone']}")
        if contacts.get("email"):
            lines.append(f"Имейл: {contacts['email']}")
        if contacts.get("website"):
            lines.append(f"Сайт: {contacts['website']}")
        lines.append("")

    activity = profile.get("activity") or {}
    if activity.get("subject"):
        lines.append("-- Предмет на дейност --")
        lines.append(activity["subject"])
        nkids = activity.get("nkids") or []
        if nkids:
            codes = ", ".join(f"{n.get('code')} - {n.get('description')}" for n in nkids)
            lines.append(f"НКИД: {codes}")
        lines.append("")

    lines.append("-- Управление и собственост --")
    lines.append("Управители:")
    lines.append(_fmt_people(profile.get("managers"), "управител"))
    if profile.get("representatives"):
        lines.append("Представители:")
        lines.append(_fmt_people(profile.get("representatives"), "представител"))
    lines.append("Съдружници/собственици:")
    partners = profile.get("partners") or []
    if partners:
        for p in partners:
            person = p.get("person", {})
            lines.append(f"  - {person.get('name', '?')} — дял: {p.get('contribution', '—')}")
    else:
        lines.append("  —")
    lines.append("")

    capital = profile.get("capital") or {}
    if capital:
        lines.append("-- Капитал --")
        lines.append(
            f"Регистриран: {_fmt_money(capital.get('amount'), capital.get('currency', 'BGN'))}   "
            f"Внесен: {_fmt_money(capital.get('paidAmount'), capital.get('currency', 'BGN'))}"
        )
        lines.append("")

    vat = profile.get("vat") or {}
    if vat.get("vat"):
        lines.append("-- ДДС регистрация --")
        lines.append(f"ДДС номер: {vat['vat']}   Дата: {vat.get('registrationDate', '—')}")
        lines.append("")

    fin = profile.get("financial")
    if fin and fin.get("financial_data"):
        lines.append("-- Финансови показатели --")
        for year in sorted(fin["financial_data"].keys(), reverse=True):
            gi = fin["financial_data"][year].get("general_info", {})
            lines.append(
                f"  {year}: приходи {_fmt_money(gi.get('revenue'))}, "
                f"печалба {_fmt_money(gi.get('profit'))}, "
                f"активи {_fmt_money(gi.get('total_assets'))}, "
                f"EBITDA {_fmt_money(gi.get('EBITDA'))}"
            )
        lines.append("")
    else:
        lines.append("-- Финансови показатели --")
        lines.append(
            "  (няма данни, извън дневния лимит, или изисква абонамент за най-новата година)"
        )
        lines.append("")

    subsidiaries = profile.get("subsidiaries") or []
    if subsidiaries:
        lines.append("-- Дъщерни фирми --")
        for s in subsidiaries:
            s_name = s.get("company_name", {}).get("name", "?")
            lines.append(f"  - {s_name} (ЕИК {s.get('uic', '?')})")
        lines.append("")

    alt = profile.get("alternative_matches") or []
    if alt:
        lines.append("-- Други намерени фирми с подобно име (провери дали не си търсил друга) --")
        for a in alt:
            lines.append(f"  - {a.get('name')} | ЕИК {a.get('uic')} | {a.get('legalForm', '')}")
        lines.append("")

    return "\n".join(lines)
