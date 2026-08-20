#!/usr/bin/env python3
"""Generate substitute storefront logos from reference logos using Gemini image-to-image.

This script intentionally works in a resumable, row-by-row fashion. It only
processes rows where:
  - use_status == "use"
  - assigned_word is present
  - reference_logo_path is present

It skips rows already generated and allows partial runs to resume safely.

Usage examples:
  python scripts/04_generate_images.py --limit 5
  python scripts/04_generate_images.py --limit 5 --dry-run
  python scripts/04_generate_images.py --brand "24 Hour Fitness"
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "strip-mall-brands.csv"
GENERATED_DIR = ROOT / "logos" / "generated"
ENV_PATH = ROOT / ".env.local"

load_dotenv(ENV_PATH, override=False)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GEMINI_IMAGE_MODEL = os.environ.get(
    "GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "word"


def normalize_word(word: str) -> str:
    cleaned = (word or "").strip()
    if not cleaned:
        return ""
    return cleaned


def is_ready_for_generation(row: dict[str, str]) -> bool:
    status = (row.get("use_status") or "").strip().lower()
    if status != "use":
        return False

    assigned_word = normalize_word(row.get("assigned_word") or "")
    if not assigned_word:
        return False

    ref_path = (row.get("reference_logo_path") or "").strip()
    if not ref_path:
        return False

    generated_path = (row.get("generated_logo_path") or "").strip()
    if generated_path:
        return False

    return True


def prompt_for_brand(brand_name: str, assigned_word: str) -> str:
    return (
        f"Use the attached reference image as the design source. "
        f"Create a clean storefront wordmark logo based on that reference design. "
        f"Match the reference logo's typography, weight, letter spacing, color palette, "
        f"high contrast, and overall brand personality as closely as possible. "
        f"Replace the original text with the exact word: '{assigned_word}'. "
        f"Keep the wordmark crisp, readable, and suitable for a retail storefront. "
        f"Do not add extra symbols, icons, slogans, or unrelated copy. "
        f"Do not change the logo into a different style or a decorative script. "
        f"Preserve the underlying letterform structure and recognizability of the reference brand, "
        f"while rendering '{assigned_word}' in that exact visual language. "
        f"The result should feel like a legitimate retail sign, not a fantasy logo."
    )


def read_csv_rows() -> list[dict[str, str]]:
    with CSV_PATH.open("r", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def write_csv_rows(rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else [
        "slug",
        "brand_name",
        "category",
        "mall_count",
        "domain",
        "reference_logo_path",
        "assigned_word",
        "generated_logo_path",
        "logo_status",
        "use_status",
    ]

    with CSV_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def find_relevant_rows(limit: int | None = None) -> list[dict[str, str]]:
    rows = read_csv_rows()
    ready_rows: list[dict[str, str]] = []

    for row in rows:
        if is_ready_for_generation(row):
            ready_rows.append(row)
            if limit is not None and len(ready_rows) >= limit:
                break

    return ready_rows


def _extract_image_bytes_from_response(response: Any) -> bytes | None:
    """Try a few common SDK response shapes and return first image bytes found."""
    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None) or []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline is not None:
                    data = getattr(inline, "data", None)
                    if isinstance(data, (bytes, bytearray)):
                        return bytes(data)
                if hasattr(part, "image"):
                    image = part.image
                    if hasattr(image, "image_bytes"):
                        data = image.image_bytes
                        if isinstance(data, (bytes, bytearray)):
                            return bytes(data)
                if hasattr(part, "bytes"):
                    data = part.bytes
                    if isinstance(data, (bytes, bytearray)):
                        return bytes(data)
    except Exception:
        pass

    if hasattr(response, "generated_images"):
        images = response.generated_images
        if isinstance(images, list) and images:
            first = images[0]
            for attr in ("image", "bytes", "data"):
                candidate = getattr(first, attr, None)
                if isinstance(candidate, (bytes, bytearray)):
                    return bytes(candidate)
                if hasattr(candidate, "data"):
                    payload = getattr(candidate, "data")
                    if isinstance(payload, (bytes, bytearray)):
                        return bytes(payload)

    return None


def generate_with_google(reference_path: Path, prompt: str, model_name: str) -> bytes:
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Add it to .env.local and retry."
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "google-genai is not installed. Run: pip install google-genai"
        ) from exc

    file_mime = "image/png"
    if reference_path.suffix.lower() == ".jpg" or reference_path.suffix.lower() == ".jpeg":
        file_mime = "image/jpeg"
    elif reference_path.suffix.lower() == ".webp":
        file_mime = "image/webp"
    elif reference_path.suffix.lower() == ".svg":
        file_mime = "image/svg+xml"

    client = genai.Client(api_key=GOOGLE_API_KEY)
    image_part = types.Part.from_bytes(
        data=reference_path.read_bytes(),
        mime_type=file_mime,
    )
    text_part = types.Part.from_text(text=prompt)

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[
                image_part,
                text_part,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                temperature=0.2,
            ),
        )
    except TypeError:
        # Some SDK versions accept content config in a slightly different manner.
        response = client.models.generate_content(
            model=model_name,
            contents=[
                image_part,
                text_part,
            ],
            config={
                "responseModalities": ["TEXT", "IMAGE"],
                "temperature": 0.2,
            },
        )

    image_data = _extract_image_bytes_from_response(response)
    if image_data is None:
        raise RuntimeError(
            "The model returned no image bytes. Check the model name, API key, and payload shape."
        )

    return image_data


def process_row(row: dict[str, str], dry_run: bool = False, delay: float = 0.0) -> dict[str, str]:
    slug = (row.get("slug") or "").strip()
    brand_name = (row.get("brand_name") or "").strip()
    assigned_word = normalize_word(row.get("assigned_word") or "")
    ref_path = (row.get("reference_logo_path") or "").strip()

    if not slug or not brand_name or not assigned_word or not ref_path:
        row["logo_status"] = "failed"
        return row

    if dry_run:
        row["logo_status"] = "pending"
        row["generated_logo_path"] = ""
        print(f"[DRY RUN] would generate: {brand_name} -> {assigned_word}")
        return row

    prompt = prompt_for_brand(brand_name, assigned_word)
    resolved_ref = ROOT / ref_path
    if not resolved_ref.exists():
        row["logo_status"] = "failed"
        row["generated_logo_path"] = ""
        return row

    word_slug = slugify(assigned_word)
    output_name = f"{slug}_{word_slug}.png"
    output_path = GENERATED_DIR / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        image_bytes = generate_with_google(
            resolved_ref, prompt, GEMINI_IMAGE_MODEL)
        output_path.write_bytes(image_bytes)
        row["generated_logo_path"] = output_path.relative_to(ROOT).as_posix()
        row["logo_status"] = "generated"
        print(f"[OK] {brand_name} -> {output_path.relative_to(ROOT).as_posix()}")
    except Exception as exc:  # pragma: no cover - network/API errors handled in main
        row["logo_status"] = "failed"
        row["generated_logo_path"] = ""
        print(f"[FAIL] {brand_name}: {exc}", file=sys.stderr)

    if delay > 0:
        time.sleep(delay)

    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate substituted storefront logos from reference logos.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only N eligible rows.")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="Optional delay between rows in seconds.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview rows without sending API requests.")
    parser.add_argument("--brand", type=str, default="",
                        help="Optional single brand name to process.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_csv_rows()

    if args.brand:
        rows = [row for row in rows if (
            row.get("brand_name") or "").strip().lower() == args.brand.strip().lower()]
        if not rows:
            print(f"No rows matched brand: {args.brand}", file=sys.stderr)
            return 1

    ready_rows = [row for row in rows if is_ready_for_generation(row)]
    if args.limit is not None:
        ready_rows = ready_rows[: args.limit]

    if not ready_rows:
        print("No eligible rows found. Check use_status, assigned_word, and reference_logo_path.")
        return 0

    print(f"Processing {len(ready_rows)} eligible row(s).")
    print(f"Using model: {GEMINI_IMAGE_MODEL}")

    for index, row in enumerate(ready_rows, start=1):
        print(f"[{index}/{len(ready_rows)}] {row.get('brand_name', '')}")
        updated_row = process_row(
            dict(row), dry_run=args.dry_run, delay=args.delay)

        for existing_index, existing_row in enumerate(rows):
            if (existing_row.get("slug") or "") == (updated_row.get("slug") or ""):
                rows[existing_index] = updated_row
                break

    write_csv_rows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
