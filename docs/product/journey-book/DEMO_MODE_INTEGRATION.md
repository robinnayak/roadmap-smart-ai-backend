# Journey Book Demo Mode Integration

This document explains how demo mode is integrated into the Journey Book generator without touching real user data.

## What Was Added

- `mode` support in generation input:
  - `mode="real"` (default)
  - `mode="demo"`
- Public endpoint:
  - `GET /journey-books/demo-preview/`
  - `GET /journey-books/demo-preview/pdf/`
- Isolated demo pipeline service:
  - `roadmap/journeybook/services/demo_mode.py`

## Request Behavior

### `mode="real"`

- Uses existing real data path:
  - `DataCollector` for DB-backed collection
  - `MetricsCalculator` for computed metrics
  - Existing generation flow and persistence

### `mode="demo"`

- Bypasses user DB collection and eligibility checks.
- Loads only in-memory demo data from:
  - `journey_book/demo_data.py` via `get_demo_journey_data()`
- Builds preview JSON from the shared fallback chapter/motivational pipeline.
- Returns response without creating `JourneyBook`, `BookChapter`, `BookAsset`, or `DerivedMilestone` records.

## Public Demo Preview Endpoint

- Route: `GET /journey-books/demo-preview/`
- Auth: not required (`AllowAny`)
- DB writes: none
- Optional query param:
  - `book_type=complete|in_progress` (defaults to `complete`)
  - `trim_size=5.5x8.5|6x9|7x10` (defaults to `6x9`)

Example:

```http
GET /journey-books/demo-preview/?book_type=complete&trim_size=6x9
```

Response now includes:
- `generation_source` (AI/fallback breakdown)
- `print_spec` (normalized trim-size print settings)

## Public Demo Preview PDF Endpoint

- Route: `GET /journey-books/demo-preview/pdf/`
- Auth: not required (`AllowAny`)
- DB writes: none (in-memory PDF response only)
- Optional query params:
  - `book_type=complete|in_progress` (defaults to `complete`)
  - `trim_size=5.5x8.5|6x9|7x10` (defaults to `6x9`)

Example:

```http
GET /journey-books/demo-preview/pdf/?book_type=in_progress&trim_size=7x10
```

## Print Flow Details

- Supported trim sizes:
  - `5.5x8.5`
  - `6x9` (default)
  - `7x10`
- PDF pages are generated at trim-size points, not fixed A4.
- Image placements use fixed trim-specific frame width/height.
- Image rendering behavior:
  - Fit-to-frame while preserving aspect ratio.
  - Centered placement inside the frame.
  - Placeholder frame rendered when image data is missing.

## Safety Guarantees

- Demo path is isolated in `services/demo_mode.py`.
- Demo payload generation does not call `DataCollector`.
- Demo JSON and demo PDF endpoints do not persist models.
- Real generation code path remains unchanged for `mode="real"`.

## Reuse / No Duplication

- Demo JSON generation is centralized in one service function:
  - `build_demo_book_payload(book_type)`
- This function is reused by:
  - `POST /api/journeybook/` when `mode="demo"`
  - `GET /journey-books/demo-preview/`
- Chapter and motivational rendering reuse existing fallback builders:
  - `ChapterFallbacks`
  - `MotivationalFallbacks`
