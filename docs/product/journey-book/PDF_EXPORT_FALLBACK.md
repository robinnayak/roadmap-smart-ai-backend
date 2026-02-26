# Journey Book PDF Export Fallback

Date: 2026-02-26

## Endpoint
- `POST /api/journeybook/{id}/export/`

## Response Contract
- `status`: `success | error`
- `pdf_url`: URL for downloadable PDF (`/api/journeybook/{id}/download/`) when available
- `demo_pdf_url`: set only when demo PDF is produced
- `is_demo_pdf`: `true` when fallback demo export is used
- `error_type`: one of:
  - `INSUFFICIENT_DATA`
  - `GENERATION_FAILED`
  - `EMPTY_CONTENT`
  - `PDF_ENGINE_ERROR`
  - `STORAGE_ERROR`
- `fallback_available`: `true` when fallback path is available

## Export Logic
1. If book is `READY` with non-empty content:
   - return existing real PDF if present, or rebuild real PDF from generated chapters.
2. If book is failed, insufficient, or empty-content:
   - export deterministic demo PDF using fallback content/template.
3. If PDF engine crashes:
   - return structured error (`PDF_ENGINE_ERROR`) with `fallback_available=true`.

## Fallback Conditions
- `days_of_data < 7` or explicit insufficient-data signal
- generated content metadata empty (`chapter_count/page_count/word_count <= 0`)
- failed generation state

## Formatting Rules (Book-like PDF)
- A4 page size
- asymmetrical print margins for binding:
  - inner margin larger than outer (`leftMargin=86`, `rightMargin=64`)
- consistent typography via embedded TTF registration when available (fallback to built-ins)
- chapter-level page breaks
- running page numbers
- consistent heading/body styles for printable output

## Determinism
- Demo export path uses deterministic fallback chapter/page content.
- Same demo input and template path produce stable structure and text ordering.
