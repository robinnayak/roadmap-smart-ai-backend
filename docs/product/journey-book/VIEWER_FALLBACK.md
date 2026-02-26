# Journey Book Viewer Fallback

Date: 2026-02-26

## Goal
Keep real Journey Book generation intact while guaranteeing a readable, book-like viewer whenever generation fails, data is insufficient, or content is empty.

## Implemented Files

### Frontend (`../roadmap-smart-planner`)
- `data/demo/journey_book_demo.json`
- `types/journey-book-content.ts`
- `components/journey-book/BookViewerModal.tsx`
- `components/journey-book/GenerateModal.tsx`
- `app/(dashboard)/journey-book/page.tsx`

### Backend (existing, unchanged by this task)
- `roadmap/journeybook/views.py`
- `roadmap/journeybook/serializers.py`
- `roadmap/journeybook/services/data_collector.py`

## Stable Book Content Schema
Demo content is now stored using a stable schema (`JourneyBookContent`) in `types/journey-book-content.ts` and concrete sample data in `data/demo/journey_book_demo.json`.

Schema includes:
- Book metadata (`title`, `subtitle`, `author`, `type`, `created_at`)
- Stats (`days`, `chapters`, `pages_estimate`, `words_estimate`)
- TOC
- 7 chapters with section headings and paragraph blocks
- Motivational pages
- Formatting hints

## UI Behavior

### 1) View Sample
- Button: `components/journey-book/BookCard.tsx` -> `onViewSample`
- Path: `app/(dashboard)/journey-book/page.tsx`
- Behavior: always opens `BookViewerModal` with demo content (`reason = manual_sample`).
- No backend dependency required.

### 2) Try Again
- Button: `components/journey-book/BookCard.tsx` -> `onRetry`
- Path: `app/(dashboard)/journey-book/page.tsx` (`handleRetry`)
- Behavior:
  1. Attempts real generation via `journeyBookApi.generate(...)`
  2. Updates list with returned book
  3. Auto-opens demo viewer when any fallback condition is true:
     - Insufficient data validation response
     - Known error code (`pdf_dependency_missing`, `generation_failed`)
     - Empty content metadata (`chapter_count/page_count/word_count <= 0`)
     - General failed generation response

### 3) Generate Modal fallback
- Path: `components/journey-book/GenerateModal.tsx`
- Real generation flow remains active.
- Added auto-fallback triggers for:
  - Insufficient data
  - Known error code
  - Empty content
  - Failed generation status

## Demo Badge + Hint
`BookViewerModal` shows a subtle banner:
- `Demo preview (insufficient data)` when eligibility/data gate fails
- Generic `Demo preview` otherwise

Hint text prompts users to add journals/routines to generate personalized output.

## Logic Summary

1. Real generation is still first-class (`journeyBookApi.generate`).
2. Demo viewer is a safe fallback layer, not a replacement.
3. User always has a readable book-like experience (title page, TOC, 7 chapters, motivational pages) even when backend generation cannot produce a downloadable PDF.
