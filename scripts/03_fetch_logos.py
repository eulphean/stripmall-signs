#!/usr/bin/env python3
"""Fetch reference logos for brands that already have a resolved domain."""

from __future__ import annotations

import csv
import os
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
BRANDFETCH_API_BASE = os.environ.get("BRANDFETCH_API_BASE", "https://api.brandfetch.io/v2")


def brandfetch_logo_payload(domain: str) -> tuple[str, str] | tuple[None, None]:
    """Fetch Brandfetch brand metadata for a domain and return a usable logo URL + type."""
    if not BRANDFETCH_API_KEY:
        return None, None

    url = f"{BRANDFETCH_API_BASE}/brands/{domain}"
    headers = {"Authorization": f"Bearer {BRANDFETCH_API_KEY}"}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return None, None

    try:
        payload = response.json()
    except ValueError:
        return None, None

    candidates: list[str] = []

    def append(value: Any) -> None:
        if not value:
            return
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, list):
            for item in value:
                append(item)
        elif isinstance(value, dict):
            for key in ("url", "src", "image", "logo", "icon"):
                if key in value and isinstance(value[key], str):
                    candidates.append(value[key])
            if "formats" in value and isinstance(value["formats"], list):
                for entry in value["formats"]:
                    append(entry)

    append(payload)

    for candidate in candidates:
        if candidate.startswith("http"):
            return candidate, infer_extension(candidate)

    return None, None


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


def download_logo(logo_url: str, slug: str) -> str:
    """Download the logo to logos/reference/{slug}{ext}."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    ext = infer_extension(logo_url)
    output_path = REFERENCE_DIR / f"{slug}{ext}"

    response = requests.get(logo_url, timeout=45)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return str(output_path.relative_to(ROOT))


def process_rows() -> list[dict[str, str]]:
    with CSV_PATH.open("r", newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    updated_rows: list[dict[str, str]] = []

    for row in rows:
        slug = (row.get("slug") or "").strip()
        brand_name = (row.get("brand_name") or "").strip()
        if not slug or not brand_name:
            continue

        domain = (row.get("domain") or "").strip()
        if not domain:
            new_row = dict(row)
            new_row["logo_status"] = "missing"
            updated_rows.append(new_row)
            continue

        new_row = dict(row)
        if not BRANDFETCH_API_KEY:
            new_row["logo_status"] = "pending"
            updated_rows.append(new_row)
            continue

        logo_url, _ = brandfetch_logo_payload(domain)
        if logo_url:
            new_row["reference_logo_path"] = download_logo(logo_url, slug)
            new_row["logo_status"] = "fetched"
        else:
            new_row["logo_status"] = "missing"

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
    rows = process_rows()
    write_rows(rows)

    fetched = sum(1 for row in rows if row.get("logo_status") == "fetched")
    missing = sum(1 for row in rows if row.get("logo_status") == "missing")
    pending = sum(1 for row in rows if row.get("logo_status") == "pending")

    print(f"Processed {len(rows)} brands; fetched={fetched}; pending={pending}; missing={missing}")


if __name__ == "__main__":
    main()
