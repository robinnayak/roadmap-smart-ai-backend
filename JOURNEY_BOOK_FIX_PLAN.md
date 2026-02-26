# Journey Book Fix Plan (Backend + Frontend End-to-End)

## Scope
This document fixes path references and required original data for full Journey Book flow across:
- Backend: `roadmap-smart-planner-backend/`
- Frontend: `roadmap-smart-planner/`

No application code changes are included in this plan update.

## Project Path Baseline
- Backend repo root: `roadmap-smart-planner-backend/`
- Backend Django root: `roadmap-smart-planner-backend/roadmap/`
- Backend Journey Book app: `roadmap-smart-planner-backend/roadmap/journeybook/`
- Frontend repo root: `roadmap-smart-planner/`
- Frontend Journey Book page: `roadmap-smart-planner/app/(dashboard)/journey-book/page.tsx`
- Frontend Journey Book components: `roadmap-smart-planner/components/journey-book/`

## Fix 1 - Standardize backend Journey Book implementation paths
- Date updated: 2026-02-26
- Status: Updated

Use these backend paths as source of truth:
- `roadmap/journeybook/models.py`
- `roadmap/journeybook/views.py`
- `roadmap/journeybook/serializers.py`
- `roadmap/journeybook/urls.py`
- `roadmap/journeybook/services/data_collector.py`
- `roadmap/journeybook/services/metrics_calculator.py`
- `roadmap/journeybook/services/ai_generator.py`
- `roadmap/journeybook/services/image_generator.py`
- `roadmap/journeybook/services/pdf_builder.py`

API mounting paths:
- Global router include: `roadmap/roadmap/urls.py`
- Journey Book base route: `/api/journeybook/`
- Common actions:
  - `GET /api/journeybook/`
  - `POST /api/journeybook/`
  - `GET /api/journeybook/eligibility/`
  - `GET /api/journeybook/{id}/download/`
  - `GET /api/journeybook/{id}/preview/`

## Fix 2 - Correct documentation output paths in backend repo
- Date updated: 2026-02-26
- Status: Updated

Use these paths in this backend repo:
- `JOURNEY_BOOK_DEBUG_NOTES.md`
- `JOURNEY_BOOK_VIEWER_FALLBACK.md`
- `JOURNEY_BOOK_PDF_EXPORT_FALLBACK.md`
- `JOURNEY_BOOK_CONTENT_SCHEMA.md`
- `JOURNEY_BOOK_DEMO_DATA_SPEC.md`

## Fix 3 - Required original data contract (backend collector)
- Date updated: 2026-02-26
- Status: Updated

Collector source: `roadmap/journeybook/services/data_collector.py`

Required original data keys:
- `profile`: `id`, `email`, `name`, `timezone`, `roadmap_start_date`, `current_situation`
- `goal` (optional): `id`, `title`, `category`, `status`, `deadline`, `start_date`, `created_at`
- `journals`: `id`, `entry_date`, `reflection_raw`, `struggle_raw`, `sentiment_score`, `sentiment_label`, `tags`, `total_word_count`
- `streaks`: `current_streak`, `longest_streak`, `last_entry_date`
- `word_frequencies`: dictionary for word cloud
- `derived_milestones`: `label`, `trigger_type`, `achieved_date`, `category`

Eligibility rules:
- `< 7 days`: blocked
- `>= 7 days`: in-progress eligible
- `>= 180 days` or goal completed/due: complete eligible

## Fix 4 - Backend failure and fallback mapping references
- Date updated: 2026-02-26
- Status: Updated

Use these references:
- Error mapping: `roadmap/journeybook/serializers.py` (`_map_error`)
- Preview payload: `roadmap/journeybook/views.py` (`preview`, `_build_preview_payload`)
- Retry context: `roadmap/journeybook/views.py` (`_retry_context`)

Known error codes:
- `pdf_dependency_missing`
- `generation_failed`

## Fix 5 - Standard future-fix layout
- Date updated: 2026-02-26
- Status: Added

Use this block for all future fixes:

```md
## Fix N - <title>
- Date updated: YYYY-MM-DD
- Status: Planned | In Progress | Blocked | Updated | Verified

Summary:
- <what was fixed>

Paths:
- <file path 1>
- <file path 2>

Notes:
- <constraints / follow-ups>
```

## Fix 6 - Frontend Journey Book implementation paths (side-by-side)
- Date updated: 2026-02-26
- Status: Updated

Frontend source-of-truth paths:
- `app/(dashboard)/journey-book/page.tsx`
- `components/journey-book/GenerateModal.tsx`
- `components/journey-book/JourneyBookList.tsx`
- `components/journey-book/BookCard.tsx`
- `components/journey-book/JourneyBookSampleModal.tsx`
- `components/journey-book/GenerationStatus.tsx`
- `components/journey-book/EligibilityBadge.tsx`
- `lib/api/journeybook.ts`
- `lib/constants/api.ts`
- `types/journeybook.ts`

## Fix 7 - End-to-end API contract alignment (frontend <-> backend)
- Date updated: 2026-02-26
- Status: Updated

Frontend endpoint constants must stay aligned with backend routes:
- List/Generate: `/api/journeybook/`
- Get one: `/api/journeybook/{id}/`
- Eligibility: `/api/journeybook/eligibility/`
- Preview: `/api/journeybook/{id}/preview/`
- Download: `/api/journeybook/{id}/download/`
- Delete: `/api/journeybook/{id}/`

Frontend response typing must include:
- Status and metadata (`status`, `metadata.page_count`, `metadata.chapter_count`, `metadata.word_count`)
- Failure UX fields (`error_code`, `error_display`, `can_preview_sample`, `can_retry`, `retry_context`)
- Download link (`download_url`)

## Fix 8 - End-to-end user flow map (side-by-side)
- Date updated: 2026-02-26
- Status: Updated

1) Generate flow:
- Frontend: `GenerateModal.tsx` -> `journeyBookApi.generate(...)`
- Backend: `JourneyBookViewSet.create` -> `_generate_sync`

2) Failure fallback flow:
- Frontend: `BookCard.tsx` + `JourneyBookSampleModal.tsx`
- Backend: serializer error mapping + `preview` endpoint

3) Download flow:
- Frontend: `book.download_url`
- Backend: `download` action returns PDF `FileResponse`

## Fix 9 - End-to-end verification checklist
- Date updated: 2026-02-26
- Status: Planned

Run this checklist after each update:
- Backend server up and route `/api/journeybook/` reachable.
- Frontend `Journey Book` page loads without API path errors.
- Create book returns either `ready` or `failed` with structured error fields.
- Failed book can open preview modal.
- Ready book exposes working `download_url`.
- Retry flow opens Generate modal with prefilled `retry_context`.
