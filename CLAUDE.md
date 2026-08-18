# Strip Mall Logo Generation Pipeline

## Goal

Generate ~200 unique substituted shop logos for a procedural strip mall
environment (Unreal Engine + PCGEx). Each logo takes a real chain's visual
identity (typography, color, containment shape) and re-renders an invented
word in that style — e.g. Subway's visual language rendered as "WAITING"
instead of "Subway". The output feeds a texture pool that PCG randomly
assigns to generated buildings.

This is an art pipeline, not a product — correctness matters less than
being able to re-run any stage cheaply and inspect results visually at
each step.

## Pipeline stages

Each script owns one stage. Every script reads `data/strip-mall-brands.csv`,
only processes rows that aren't already done for that stage, and updates
the relevant status column when it finishes a row. **No script should ever
require a full re-run from scratch** — killing a script partway through and
re-running it later must resume, not restart.

1. **`01_build_brand_csv.py`** — Parse https://www.themalldirectory.com/stores
   into `data/strip-mall-brands.csv`. Columns: `slug`, `brand_name`,
   `category`, `mall_count`. Take the top ~200 by `mall_count` (or all 477,
   TBD — start with everything, filter later).
2. **`02_resolve_domains.py`** — Resolve a canonical `domain` for each brand
   using the Brandfetch API, reading `BRANDFETCH_API_KEY` and
   `BRANDFETCH_API_BASE` from `.env.local`. Write back the normalized domain
   to `data/strip-mall-brands.csv` for downstream logo lookups.
3. **`02_fetch_logos.py`** — For each row with a resolved domain, fetch the
   reference logo from Brandfetch, save it to `logos/reference/{slug}.{ext}`,
   update `reference_logo_path` and `logo_status` (`fetched` / `missing`).
4. **`03_assign_words.py`** — Load `data/word_bank.csv` (a plain list of
   invented words, no shop mapping yet — build this list separately,
   doesn't need to be finalized before writing this script). Shuffle and
   assign one unique word per brand row, no repeats within a run. Write
   `assigned_word` column. Re-runnable to reshuffle assignments.
5. **`04_generate_images.py`** — For each row with a fetched reference and
   an assigned word, call Nano Banana Pro (Gemini 3 Pro Image) via the
   Batch API, image-to-image: reference logo + prompt instructing it to
   match the reference's letterform style/weight/color and render the
   assigned word. Save to `logos/generated/{slug}_{word_slug}.png`, update
   `generated_logo_path` and `logo_status` (`generated` / `failed`).
6. **`05_crop_prep.py`** — Optional cleanup pass, split into two modes:
   - `--pre`: crop/isolate wordmark-only from raw reference logos before
     generation (drop icon marks, tighten to lettering).
   - `--post`: trim/standardize canvas on generated outputs before Unreal
     import.

## Data schema — `data/strip-mall-brands.csv`

| column | meaning |
|---|---|
| `slug` | canonical key used in every filename, everywhere |
| `brand_name` | display name, e.g. "Subway" |
| `category` | one of ~19 tags (apparel, fast_food, footwear, jewelry_accessories, home_goods, beauty, casual_dining, electronics_mobile, optical, services, grocery, sporting_goods, fitness, health, pet, auto_parts, books, department_store, specialty_retail) — metadata for downstream prop/dressing systems, not used by the logo pipeline itself |
| `mall_count` | frequency signal from source data — informed brand selection, not currently used for spawn weighting |
| `domain` | resolved domain for logo lookup |
| `reference_logo_path` | path to fetched original logo |
| `assigned_word` | invented word for this brand |
| `generated_logo_path` | path to final substituted logo |
| `logo_status` | pipeline state per row: `pending` / `fetched` / `missing` / `generated` / `failed` |

## Conventions

- **Naming**: reference/cropped files are `{slug}.ext` — one canonical file
  per brand, never overwritten. Generated files are `{slug}_{word_slug}.png`
  — encodes which word was used, so regenerating with a different word never
  collides with or silently overwrites a prior attempt.
- **Idempotency over cleverness**: prefer scripts that check status and skip
  finished rows over scripts that assume a clean run every time.
- **Reference logos stay wordmark-focused where possible** — crop out
  icon/symbol marks before generation so the model matches letterform style
  rather than getting pulled toward preserving icon composition.
- **Don't over-fit the word-to-brand pairing.** Assignment is intentionally
  arbitrary/random, not hand-matched — the goal is indifferent pairing, not
  clever puns. Resist the urge to manually curate matches.
- **Test before committing to full batches.** Character-count mismatch
  between short brand names (IHOP) and longer invented words (DREAMING) is
  an open, unverified risk — run a small spread of length combinations
  through step 4 before running all ~200 through the Batch API.

## External services

- **Brandfetch** — domain resolution and logo lookup via the API. This project
  reads `BRANDFETCH_API_KEY` and `BRANDFETCH_API_BASE` from `.env.local`.
- **Nano Banana Pro** = Gemini 3 Pro Image (`gemini-3-pro-image-preview`),
  via `google-genai` SDK. Use the Batch API for the full run (50% cost
  discount vs. sync calls) once the prompt template is validated on a small
  test batch.

## Not yet decided (don't block on these)

- Whether `mall_count` weighting matters at PCG spawn time (currently: no,
  spawn is unique-per-batch, not frequency-weighted).
- Final word bank size/content (~200 target, seed list exists, needs
  expansion).
- Whether category should loosely correlate with word register, or stay
  fully random.

## Getting started

```bash
mkdir -p strip-mall-logos/{data,logos/reference,logos/reference-cropped,logos/generated,scripts,logs}
cd strip-mall-logos
# place this file as CLAUDE.md in the project root
git init
claude
```

Once inside Claude Code, start with:

> Read CLAUDE.md. Let's build `01_build_brand_csv.py` first — fetch and
> parse https://www.themalldirectory.com/stores into the CSV schema
> described.

Work through the scripts in order (01 → 02 → 03 → 04), testing each stage
on a small subset (5-10 rows) before running it against the full brand
list.
