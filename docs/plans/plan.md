# Strip Mall Logo Generation Pipeline

## Objective
Build a resumable pipeline that generates a large set of substituted shop logos for a procedural strip mall environment, using real brand visual languages as a reference and re-rendering invented words in the same style.

## Scope
- Parse source mall-brand data into a canonical CSV
- Fetch and store reference logos for each brand
- Assign invented words to each brand without duplication within a run
- Generate substituted wordmark variants using image generation
- Add optional crop/prep steps for cleaner reference and final assets
- Keep every stage re-runnable and resumable without full restart

## Pipeline stages

### 1. Build brand CSV
- Script: 01_build_brand_csv.py
- Source: https://www.themalldirectory.com/stores
- Output: data/strip-mall-brands.csv
- Required columns:
  - slug
  - brand_name
  - category
  - mall_count
  - domain
  - reference_logo_path
  - assigned_word
  - generated_logo_path
  - logo_status
- Use top available brands initially and keep the pipeline flexible for later filtering

### 2. Resolve brand domains
- Script: 02_resolve_domains.py
- For each brand row, hit the Brandfetch search API and resolve a canonical domain
- Load `BRANDFETCH_API_KEY` and `BRANDFETCH_API_BASE` from `.env.local`
- Normalize and write the resolved domain back to the CSV
- This step is intentionally separated from logo downloads so domain resolution can be rerun independently

### 3. Fetch reference logos
- Script: 02_fetch_logos.py
- For each brand row with a resolved domain, fetch the reference logo from Brandfetch
- Save reference files into logos/reference/{slug}.{ext}
- Update reference_logo_path and logo_status
- Status values: pending / fetched / missing
- Skip rows already processed; resume cleanly

### 4. Assign invented words
- Script: 03_assign_words.py
- Load data/word_bank.csv
- Shuffle and assign a unique word per brand
- Re-runnable so it can reshuffle assignments without reworking earlier steps
- Store in assigned_word column

### 5. Generate substituted logos
- Script: 04_generate_images.py
- For each brand with a reference logo and an assigned word:
  - call image generation using the reference logo as the style source
  - prompt the model to retain the reference's letterform behavior, weight, and color while substituting the assigned word
- Save output to logos/generated/{slug}_{word_slug}.png
- Update generated_logo_path and logo_status
- Status values: generated / failed
- Validate on a small subset before running the full batch

### 6. Optional crop/prep pass
- Script: 05_crop_prep.py
- Modes:
  - --pre: crop reference logos to isolate wordmarks before generation
  - --post: trim / normalize generated outputs for Unreal import
- This is optional cleanup and should not block the core pipeline

## Folder structure
- data/
- logos/reference/
- logos/reference-cropped/
- logos/generated/
- scripts/
- logs/

## Naming conventions
- Reference files: {slug}.{ext}
- Generated files: {slug}_{word_slug}.png
- Keep one canonical file per brand reference and never overwrite it silently
- Generated files should encode the assigned word to avoid collision

## Resumability requirements
- No script should require a clean full re-run from scratch
- Each stage should skip rows already completed for that stage
- Status columns drive progress and resume logic
- Killing and restarting a script must not lose progress

## Key design principles
- Prioritize idempotency over cleverness
- Prefer wordmark-focused references over decorative icon marks
- Keep brand-to-word assignments arbitrary and random rather than curated
- Test image-generation behavior with short/long word combinations before batch processing
- Treat the pipeline as a reusable procedural art tool, not as a one-off product generation task

## External service assumptions
- Brandfetch as the domain and logo lookup source
- Local env secrets stored in `.env.local` via `BRANDFETCH_API_KEY` and `BRANDFETCH_API_BASE`
- Google Gemini 3 Pro Image via the Batch API for generation
- Do not reintroduce deprecated or dead free logo APIs

## Success criteria
- Project can be initialized in this repository with the expected folder structure
- Brand CSV can be built from the source mall listing
- Logos can be fetched and stored per brand
- Words can be assigned without duplication
- Generated substitute logos can be batched and visually validated
- Any stage can be rerun or resumed without resetting the whole pipeline

## Immediate next actions
1. Create the project folder structure
2. Add the project brief/specification file
3. Implement stage 01: brand CSV builder
4. Verify on a small subset before expanding to the full catalog
