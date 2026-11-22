#!/usr/bin/env python3
"""Synchronize catalog counts inside README.md with ios_debloat/catalog.py."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ios_debloat.catalog import build_catalog, catalog_stats  # noqa: E402


def compute_counts() -> dict[str, int]:
    """Compute all catalog counts displayed in README.md."""
    secs = build_catalog("all")
    stats = catalog_stats(secs)
    restrictions = [it for s in secs for it in s.items if it.kind == "restriction"]
    tel_unsup = sum(1 for it in restrictions if "telemetry" in it.presets and not it.supervised)
    bal_unsup = sum(1 for it in restrictions if "balanced" in it.presets and not it.supervised)
    return {
        "restrictions_total": stats.restrictions_total,
        "restrictions_unsupervised": stats.restrictions_unsupervised,
        "restrictions_supervised": stats.restrictions_supervised,
        "telemetry_total": stats.telemetry_preset,
        "telemetry_unsup": tel_unsup,
        "balanced_total": stats.balanced_preset,
        "balanced_unsup": bal_unsup,
        "dns_presets": stats.dns_presets,
        "stock_apps": stats.stock_apps,
        "watch_checklist": stats.watch_checklist,
        "watch_profile_keys": stats.watch_profile_keys,
        "telemetry_daemons": stats.telemetry_daemons,
    }


def apply_readme_counts(text: str, counts: dict[str, int]) -> str:
    """Replace `<!-- sync:KEY -->...<!-- /sync:KEY -->` spans in `text`."""
    pattern = re.compile(r"<!--\s*sync:([a-z0-9_]+)\s*-->.*?<!--\s*/sync:\1\s*-->")

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in counts:
            raise KeyError(f"Unknown README sync key: {key!r}")
        return f"<!-- sync:{key} -->{counts[key]}<!-- /sync:{key} -->"

    return pattern.sub(_sub, text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync catalog counts in README.md")
    parser.add_argument("--check", action="store_true", help="exit 1 if README.md is out of sync")
    args = parser.parse_args(argv)

    readme = ROOT / "README.md"
    if not readme.is_file():
        print(f"missing {readme}", file=sys.stderr)
        return 1

    original = readme.read_text(encoding="utf-8")
    updated = apply_readme_counts(original, compute_counts())

    if args.check:
        if original != updated:
            print("README.md catalog counts are out of sync. Run: python3 extras/sync_readme.py", file=sys.stderr)
            return 1
        print("README.md catalog counts are up to date.")
        return 0

    if original != updated:
        readme.write_text(updated, encoding="utf-8")
        print("Updated README.md catalog counts.")
    else:
        print("README.md already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
