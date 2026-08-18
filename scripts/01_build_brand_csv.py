#!/usr/bin/env python3
"""Build the initial strip-mall brand CSV from The Mall Directory."""

from __future__ import annotations

import csv
import html
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "strip-mall-brands.csv"
SOURCE_URL = "https://www.themalldirectory.com/stores"

CSV_COLUMNS = [
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


def slugify(value: str) -> str:
    """Turn a store name into a stable slug used in filenames and CSV IDs."""
    text = html.unescape(value).strip().lower()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text


def extract_brands(html_text: str) -> list[dict[str, str | int]]:
    """Extract only real brand entries from the A-Z directory list."""
    stores: list[dict[str, str | int]] = []
    seen: set[str] = set()

    all_brands_index = html_text.lower().find("all brands")
    if all_brands_index == -1:
        raise RuntimeError("Could not find the All brands A–Z section in the page source.")

    section_html = html_text[all_brands_index:]

    pattern = re.compile(
        r'href="/stores/([^"]+)"[^>]*>\s*(.*?)\s*<span[^>]*class="[^"]*text-muted[^"]*"[^>]*>\s*\(\s*<!--\s*-->\s*(\d+)\s*<!--\s*-->\s*\)\s*</span>\s*</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(section_html):
        slug, raw_name, raw_count = match.groups()
        if slug.lower() == "all-brands-a-z":
            continue

        name = html.unescape(re.sub(r"<.*?>", "", raw_name)).strip()
        if not name or not slug:
            continue

        normalized_slug = slugify(name)
        if normalized_slug in seen:
            continue
        seen.add(normalized_slug)

        stores.append(
            {
                "slug": normalized_slug,
                "brand_name": name,
                "mall_count": int(raw_count),
            }
        )

    stores.sort(key=lambda row: str(row["brand_name"]).lower())
    return stores


def fetch_store_page(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def write_csv(rows: list[dict[str, str | int]]) -> Path:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    "slug": row["slug"],
                    "brand_name": row["brand_name"],
                    "category": "",
                    "mall_count": row["mall_count"],
                    "domain": "",
                    "reference_logo_path": "",
                    "assigned_word": "",
                    "generated_logo_path": "",
                    "logo_status": "",
                }
            )

    return OUTPUT_PATH


def main() -> None:
    html_text = fetch_store_page(SOURCE_URL)
    stores = extract_brands(html_text)

    if not stores:
        raise RuntimeError("No stores found on source page. Check the page structure.")

    output_path = write_csv(stores)
    print(f"Wrote {len(stores)} brands to {output_path}")


if __name__ == "__main__":
    main()
