#!/usr/bin/env python3
"""Pre-convert SVG reference logos to PNG before image generation.

Gemini's image models don't accept image/svg+xml as an input format
(only PNG/JPEG/WebP), so any row whose reference_logo_path is an .svg
file needs a rasterized PNG counterpart before 04_generate_images.py
can use it.

This script only touches rows where:
  - use_status == "use"
  - reference_logo_path ends in .svg

It converts logos/reference/{slug}.svg -> logos/reference/{slug}.png
(the original .svg is left in place) and updates reference_logo_path
in the CSV to point at the new .png.

Resumable: if the target .png already exists on disk, the row is
considered already converted and is skipped (its CSV path is just
pointed at the existing file rather than re-running the conversion).

Usage:
  python scripts/convert_svg_references.py --limit 10
  python scripts/convert_svg_references.py --limit 10 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "strip-mall-brands.csv"

DEFAULT_SCALE = 2.0


def read_csv_rows() -> list[dict[str, str]]:
    with CSV_PATH.open("r", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def write_csv_rows(rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys())
    with CSV_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def is_convertible(row: dict[str, str]) -> bool:
    status = (row.get("use_status") or "").strip().lower()
    if status != "use":
        return False
    if not (row.get("assigned_word") or "").strip():
        return False
    ref_path = (row.get("reference_logo_path") or "").strip()
    return ref_path.lower().endswith(".svg")


# Illustrator-exported SVGs sometimes declare xmlns values that aren't
# real URIs (e.g. xmlns:sfw="ns_sfw;"), which rsvg-convert rejects as
# invalid XML even though the visible artwork doesn't depend on them.
_BOGUS_XMLNS_RE = re.compile(r'\s+xmlns(:\w+)?="(?!https?://)[^"]*"')


def _sanitize_svg(svg_bytes: bytes) -> bytes:
    text = svg_bytes.decode("utf-8", errors="replace")
    text = _BOGUS_XMLNS_RE.sub("", text)
    return text.encode("utf-8")


def convert_svg_to_png(svg_path: Path, png_path: Path, scale: float = DEFAULT_SCALE) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize_svg(svg_path.read_bytes())

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        tmp.write(sanitized)
        tmp_path = Path(tmp.name)

    try:
        subprocess.run(
            [
                "rsvg-convert",
                "--zoom", str(scale),
                "--output", str(png_path),
                str(tmp_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert SVG reference logos to PNG for rows marked use_status=use.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only N eligible rows.")
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE,
                        help="Zoom factor passed to rsvg-convert (default: 2.0).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview rows without converting or writing the CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if shutil.which("rsvg-convert") is None and not args.dry_run:
        print(
            "rsvg-convert not found. Install it with: brew install librsvg",
            file=sys.stderr,
        )
        return 1

    rows = read_csv_rows()
    eligible = [row for row in rows if is_convertible(row)]
    if args.limit is not None:
        eligible = eligible[: args.limit]

    if not eligible:
        print("No eligible SVG reference rows found (use_status=use, .svg reference).")
        return 0

    print(f"Processing {len(eligible)} eligible row(s).")

    converted = 0
    reused = 0
    failed = 0

    for index, row in enumerate(eligible, start=1):
        slug = (row.get("slug") or "").strip()
        brand_name = (row.get("brand_name") or "").strip()
        ref_path = (row.get("reference_logo_path") or "").strip()
        svg_path = ROOT / ref_path
        png_path = svg_path.with_suffix(".png")

        print(f"[{index}/{len(eligible)}] {brand_name} ({slug})")

        if args.dry_run:
            action = "reuse existing png" if png_path.exists() else "convert"
            print(f"  [DRY RUN] would {action}: {svg_path.name} -> {png_path.name}")
            continue

        if not svg_path.exists():
            print(f"  [FAIL] source svg missing: {svg_path}", file=sys.stderr)
            failed += 1
            continue

        if png_path.exists():
            reused += 1
        else:
            try:
                convert_svg_to_png(svg_path, png_path, scale=args.scale)
                converted += 1
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
                print(f"  [FAIL] {brand_name}: {stderr.strip()}", file=sys.stderr)
                failed += 1
                continue

        for existing_row in rows:
            if (existing_row.get("slug") or "") == slug:
                existing_row["reference_logo_path"] = png_path.relative_to(
                    ROOT).as_posix()
                break

        print(f"  [OK] {svg_path.name} -> {png_path.relative_to(ROOT).as_posix()}")

    if not args.dry_run:
        write_csv_rows(rows)
        print(
            f"Done. converted={converted} reused={reused} failed={failed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
