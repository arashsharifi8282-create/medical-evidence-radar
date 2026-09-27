"""Explicit, separate FDA metadata CLI. API key: OPENFDA_API_KEY (local only)."""
import argparse
import sys
from pathlib import Path

from app.services.regulatory_persistence import save_snapshot
from app.sources.regulatory.fda_openfda import FDAClient
from app.sources.regulatory.validation import RegulatoryError


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description="Explicit Drugs@FDA metadata observation")
    parser.add_argument("--source", required=True, choices=("fda-drugsfda",))
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--query")
    choice.add_argument("--manifest", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--data-dir", type=Path, default=Path("data/regulatory"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/regulatory"))
    parser.add_argument("--name", default="fda_observation")
    args = parser.parse_args(argv)
    try:
        if args.manifest and args.limit != 100:
            raise RegulatoryError("invalid_scope")
        adapter = client if client is not None else FDAClient()
        result = adapter.bulk() if args.manifest else adapter.query(args.query, limit=args.limit)
        if args.save:
            save_snapshot(result, args.data_dir, args.report_dir, args.name)
        else:
            print(f"Validated {len(result['records'])} FDA application metadata records; no files saved")
        return 0
    except RegulatoryError as error:
        print(f"B7 error: {error.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())