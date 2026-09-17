"""Command-line interface for native input preparation."""
import argparse
import json
import sys

from . import __version__
from .models import IntakeError
from .pipeline import prepare


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Archive CSV/XLSX inputs and export native L1 records.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", required=True, help="Path to an intake-v1 JSON catalogue")
    parser.add_argument("--output", default="artifacts/intake", help="Output root (default: artifacts/intake)")
    args = parser.parse_args(argv)
    try:
        summary = prepare(args.config, args.output)
    except IntakeError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 2 if exc.code.startswith("CONFIG_") else 1
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if summary["status"] == "prepared" else 1
