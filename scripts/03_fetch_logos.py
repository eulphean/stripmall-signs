#!/usr/bin/env python3
"""Fetch reference logos for brands that already have a resolved domain."""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "strip-mall-brands.csv"
REFERENCE_DIR = ROOT / "logos" / "reference"
ENV_PATH = ROOT / ".env.local"

load_dotenv(ENV_PATH, override=False)
BRANDFETCH_API_KEY = os.environ.get("BRANDFETCH_API_KEY")
BRANDFETCH_API_BASE = os.environ.get(
    "BRANDFETCH_API_BASE", "https://api.brandfetch.io/v2")
BRANDFETCH_CLIENT_ID = os.environ.get("BRANDFETCH_CLIENT_ID")


def infer_extension(url: str) -> str:
    lower = url.lower()
    if lower.endswith(".svg"):
        return ".svg"
    if lower.endswith(".png"):
        return ".png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return ".jpg"
    if lower.endswith(".webp"):
        return ".webp"
    return ".png"


def extract_first_industry_slug(payload: Any) -> str:
    """Return the first industry slug Brandfetch provides, if available."""
    if not isinstance(payload, dict):
        return ""

    for key in ("industries", "industry", "categories", "category"):
        value = payload.get(key)
        if not value:
            continue

        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    if item.get("slug"):
                        return str(item["slug"])
                    if item.get("name"):
                        return str(item["name"]).lower().replace(" ", "-")
                elif isinstance(item, str):
                    return item.strip().lower().replace(" ", "-")

        if isinstance(value, dict):
            if value.get("slug"):
                return str(value["slug"])
            if value.get("name"):
                return str(value["name"]).lower().replace(" ", "-")

        if isinstance(value, str):
            return value.strip().lower().replace(" ", "-")

    return ""


def coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = "".join(ch for ch in value if ch.isdigit() or ch in ".-")
        if not cleaned:
            return None
        try:
            return int(float(cleaned))
        except ValueError:
            return None
    return None


def get_ratio_from_entry(entry: dict[str, Any]) -> float | None:
    width = None
    height = None

    for key in ("width", "w"):
        if key in entry:
            width = coerce_int(entry.get(key))
            if width:
                break
    for key in ("height", "h"):
        if key in entry:
            height = coerce_int(entry.get(key))
            if height:
                break

    if width and height and height > 0:
        return width / height

    if "formats" in entry and isinstance(entry["formats"], list):
        for item in entry["formats"]:
            if isinstance(item, dict):
                width = coerce_int(item.get("width") or item.get("w"))
                height = coerce_int(item.get("height") or item.get("h"))
                if width and height and height > 0:
                    return width / height

    return None


def is_dark_theme(entry: dict[str, Any]) -> bool:
    text = " ".join(str(v) for v in entry.values()
                    if isinstance(v, (str, int, float))).lower()
    raw_theme = str(entry.get("theme") or entry.get("type") or "").lower()
    if "dark" in raw_theme or "black" in raw_theme:
        return True
    if "light" in raw_theme and "dark" not in raw_theme:
        return False
    if "dark" in text:
        return True
    return False


def is_horizontal(entry: dict[str, Any]) -> bool:
    ratio = get_ratio_from_entry(entry)
    return ratio is not None and ratio >= 1.5


def choose_logo_url(payload: Any) -> tuple[str | None, str | None]:
    """Choose the best dark logo URL and preserve the Brandfetch format extension."""
    if not isinstance(payload, dict):
        return None, None

    logos = payload.get("logos")
    if not isinstance(logos, list):
        return None, None

    best_url: str | None = None
    best_format: str | None = None
    best_score: tuple[int, int, float] | None = None

    for logo_entry in logos:
        if not isinstance(logo_entry, dict):
            continue

        logo_type = str(logo_entry.get("type") or "").lower()
        theme = str(logo_entry.get("theme") or "").lower()
        formats = logo_entry.get("formats")
        if not isinstance(formats, list):
            continue

        for format_entry in formats:
            if not isinstance(format_entry, dict):
                continue

            src = format_entry.get("src") or format_entry.get("url")
            if not isinstance(src, str) or not src.startswith("http"):
                continue

            fmt = str(format_entry.get("format") or "").lower().strip()
            width = coerce_int(format_entry.get("width")
                               or format_entry.get("w"))
            height = coerce_int(format_entry.get("height")
                                or format_entry.get("h"))
            ratio = (width / height) if width and height and height > 0 else None
            horizontal = ratio is not None and ratio >= 1.5
            dark = "dark" in theme or "black" in theme

            score = (
                0 if dark and logo_type == "logo" else 1,
                0 if horizontal else 1,
                abs((ratio or 0.0) - 4.0) if ratio is not None else 999.0,
            )

            if best_score is None or score < best_score:
                best_url = src
                best_format = fmt or infer_extension(src)
                best_score = score

    return best_url, best_format


def brandfetch_logo_payload(domain: str) -> tuple[str | None, str | None, str]:
    """Return the selected logo URL, extension, and industry slug for a domain."""
    if not BRANDFETCH_API_KEY:
        return None, None, ""

    url = f"{BRANDFETCH_API_BASE.rstrip('/')}/brands/{domain}"
    headers = {"Authorization": f"Bearer {BRANDFETCH_API_KEY}"}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return None, None, ""

    try:
        payload = response.json()
    except ValueError:
        return None, None, ""

    category = extract_first_industry_slug(payload)
    logo_url, logo_format = choose_logo_url(payload)
    if not logo_url:
        return None, None, category

    return logo_url, logo_format or infer_extension(logo_url), category


def download_logo(logo_url: str, slug: str, ext: str | None = None) -> str:
    """Download a logo while preserving the Brandfetch-returned format."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    output_ext = ext or infer_extension(logo_url)
    output_path = REFERENCE_DIR / \
        f"{slug}{output_ext if output_ext.startswith('.') else f'.{output_ext}'}"

    response = requests.get(logo_url, timeout=45)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return output_path.relative_to(ROOT).as_posix()


def should_skip_row(row: dict[str, str]) -> bool:
    """Skip only rows already complete or definitively unresolved."""
    if (row.get("reference_logo_path") or "").strip():
        return True

    status = (row.get("logo_status") or "").strip().lower()
    return status in {"fetched", "missing", "generated", "failed"}


def process_rows(limit: int | None = None, delay: float = 0.5) -> list[dict[str, str]]:
    with CSV_PATH.open("r", newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    updated_rows: list[dict[str, str]] = []
    processed = 0

    for row in rows:
        slug = (row.get("slug") or "").strip()
        brand_name = (row.get("brand_name") or "").strip()
        if not slug or not brand_name:
            updated_rows.append(dict(row))
            continue

        if should_skip_row(row):
            updated_rows.append(dict(row))
            continue

        if limit is not None and processed >= limit:
            new_row = dict(row)
            new_row["logo_status"] = "pending"
            updated_rows.append(new_row)
            continue

        new_row = dict(row)
        domain = (row.get("domain") or "").strip()
        if not domain:
            new_row["logo_status"] = "missing"
            updated_rows.append(new_row)
            continue

        if delay > 0 and processed > 0:
            time.sleep(delay)

        if not BRANDFETCH_API_KEY:
            new_row["logo_status"] = "pending"
            updated_rows.append(new_row)
            continue

        logo_url, ext, category_slug = brandfetch_logo_payload(domain)
        if category_slug:
            new_row["category"] = category_slug

        if logo_url:
            new_row["reference_logo_path"] = download_logo(logo_url, slug, ext)
            new_row["logo_status"] = "fetched"
        else:
            new_row["logo_status"] = "missing"

        processed += 1
        updated_rows.append(new_row)

    return updated_rows


def write_rows(rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "slug",
        "brand_name",
        "category",
        "mall_count",
        "domain",
        "reference_logo_path",
        "assigned_word",
        "generated_logo_path",
        "logo_status",
    ]

    with CSV_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "slug": row.get("slug", ""),
                "brand_name": row.get("brand_name", ""),
                "category": row.get("category", ""),
                "mall_count": row.get("mall_count", ""),
                "domain": row.get("domain", ""),
                "reference_logo_path": row.get("reference_logo_path", ""),
                "assigned_word": row.get("assigned_word", ""),
                "generated_logo_path": row.get("generated_logo_path", ""),
                "logo_status": row.get("logo_status", ""),
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only fetch this many new logos this run (for testing on a small subset)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to sleep between live logo fetches (default: 0.5)",
    )
    args = parser.parse_args()

    rows = process_rows(limit=args.limit, delay=args.delay)
    write_rows(rows)

    fetched = sum(1 for row in rows if row.get("logo_status") == "fetched")
    missing = sum(1 for row in rows if row.get("logo_status") == "missing")
    pending = sum(1 for row in rows if row.get("logo_status") == "pending")

    print(
        f"Processed {len(rows)} brands; fetched={fetched}; pending={pending}; missing={missing}")


if __name__ == "__main__":
    main()
