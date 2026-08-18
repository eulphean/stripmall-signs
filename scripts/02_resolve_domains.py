#!/usr/bin/env python3
"""Resolve a canonical domain for each brand before any logo fetch step."""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "strip-mall-brands.csv"
ENV_PATH = ROOT / ".env.local"

load_dotenv(ENV_PATH, override=False)
BRANDFETCH_API_BASE = os.environ.get("BRANDFETCH_API_BASE", "https://api.brandfetch.io/v2")
BRANDFETCH_CLIENT_ID = os.environ.get("BRANDFETCH_CLIENT_ID")


def normalize_domain(value: str) -> str:
    """Normalize a discovered domain to a host-only value without scheme or path."""
    domain = value.strip().lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = re.sub(r"/.*$", "", domain)
    domain = re.sub(r"[^a-z0-9.-]", "", domain)
    return domain.strip(".")


def resolve_domain(brand_name: str) -> str:
    """Resolve a canonical domain for a brand name using the Brandfetch search API."""
    if not BRANDFETCH_CLIENT_ID:
        return ""

    # Free search API: GET /v2/search/{query}?c={clientId} — no Authorization
    # header, auth is the clientId query param. Distinct from the paid Brand
    # API (which uses BRANDFETCH_API_KEY as a Bearer token).
    url = f"{BRANDFETCH_API_BASE}/search/{quote(brand_name)}"
    params = {"c": BRANDFETCH_CLIENT_ID}

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return ""

    try:
        payload = response.json()
    except ValueError:
        return ""

    if isinstance(payload, dict):
        payload = payload.get("brands", [payload])

    for item in payload:
        if not isinstance(item, dict):
            continue
        for field in ("domain", "website", "url", "name"):
            value = item.get(field)
            if value:
                normalized = normalize_domain(str(value))
                if normalized:
                    return normalized

    return ""


def update_rows(limit: int | None = None, delay: float = 1.6) -> list[dict[str, str]]:
    """Resolve missing domains. Rows that already have a domain are skipped
    entirely (no request made) — safe to kill and re-run partway through.

    `limit` caps how many *new* lookups are made this run (existing domains
    don't count against it) — useful for testing on a small slice.
    `delay` is seconds slept between live lookups, to stay well under
    Brandfetch's 200-requests-per-5-minutes-per-IP limit (~1.5s/request).
    """
    with CSV_PATH.open("r", newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    updated_rows: list[dict[str, str]] = []
    lookups_done = 0
    for row in rows:
        brand_name = (row.get("brand_name") or "").strip()
        slug = (row.get("slug") or "").strip()
        if not brand_name or not slug:
            updated_rows.append(dict(row))
            continue

        domain = normalize_domain((row.get("domain") or "").strip())
        if not domain and (limit is None or lookups_done < limit):
            if lookups_done > 0:
                time.sleep(delay)
            domain = resolve_domain(brand_name)
            lookups_done += 1

        new_row = dict(row)
        new_row["domain"] = domain
        updated_rows.append(new_row)
        write_rows(updated_rows + rows[len(updated_rows):])

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
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only resolve this many new domains this run (for testing on a small slice)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.6,
        help="Seconds to sleep between live lookups (default: 1.6, ~200/5min limit)",
    )
    args = parser.parse_args()

    rows = update_rows(limit=args.limit, delay=args.delay)
    write_rows(rows)

    filled = sum(1 for row in rows if row.get("domain"))
    empty = len(rows) - filled
    print(f"Resolved domains for {filled} brands; {empty} remain empty")


if __name__ == "__main__":
    main()
