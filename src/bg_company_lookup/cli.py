"""CLI: python -m bg_company_lookup.cli <ЕИК или име> [--json]"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from bg_company_lookup.core import CompanyNotFound, LookupServiceError, format_profile, lookup


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Справка за българска фирма по ЕИК или име")
    parser.add_argument("query", help="ЕИК (9 или 13 цифри) или име на фирма")
    parser.add_argument("--json", action="store_true", help="изход като JSON вместо четим текст")
    args = parser.parse_args(argv)

    try:
        result = lookup(args.query)
    except (CompanyNotFound, RuntimeError, LookupServiceError) as e:
        print(f"Грешка: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_profile(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
