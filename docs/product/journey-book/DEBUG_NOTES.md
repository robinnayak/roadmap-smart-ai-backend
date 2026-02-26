# Journey Book Debug Notes

Date: 2026-02-26
Repo: `roadmap-smart-planner-backend`

## 1) Feature implementation map (with file evidence)

### Frontend (sibling repo: `../roadmap-smart-planner`)
- Journey Book page: `app/(dashboard)/journey-book/page.tsx`
  - Uses `journeyBookApi` and mounts sample modal (`JourneyBookSampleModal`) (`app/(dashboard)/journey-book/page.tsx:8-10,162`).
- API client: `lib/api/journeybook.ts`
  - Methods: `list`, `generate`, `getOne`, `preview`, `getEligibility`, `remove`.
- Endpoint constants: `lib/constants/api.ts:134-140`
  - `/api/journeybook/`, `/api/journeybook/{id}/`, `/download/`, `/preview/`, `/eligibility/`, delete.
- Failure UI text in card:
  - `Journey Book generation failed.` (`components/journey-book/BookCard.tsx:70`)
  - `PDF export is temporarily unavailable. You can view a sample and try again.` (`components/journey-book/BookCard.tsx:33`)
- Sample modal implementation: `components/journey-book/JourneyBookSampleModal.tsx`.

### Backend (this repo)
- Route mount: `roadmap/roadmap/urls.py:14`
  - `path('api/journeybook/', include('journeybook.urls', namespace='journeybook'))`
- Router registration: `roadmap/journeybook/urls.py:9`
  - Viewset registered as `JourneyBookViewSet`.
- Endpoints implemented in `roadmap/journeybook/views.py`:
  - `create` (`JourneyBookViewSet.create`) at `views.py:41`
  - `download` action at `views.py:105`
  - `preview` action at `views.py:117`
  - synchronous generation path `_generate_sync` at `views.py:128`
- PDF export code:
  - `roadmap/journeybook/services/pdf_builder.py`
  - `PDFBuilder.build` raises: `ReportLab is required to build Journey Book PDFs.` when dependency missing (`pdf_builder.py:21`).

### Job / worker model (Journey Book)
- No Celery/background queue is implemented for Journey Book generation.
- Evidence: `JourneyBookViewSet.create` directly calls `self._generate_sync(...)` in request flow (`roadmap/journeybook/views.py:82`).
- This means generation is synchronous inside the API request.

## 2) Reproduced failure state from API calls

All calls below were executed with DRF `APIClient` against Django settings in this repo, on 2026-02-26.

### A) Technical failure reproduced (matches UI "PDF export temporarily unavailable")

Request:
- Endpoint: `POST /api/journeybook/`
- Payload:
```json
{
  "goal_id": "77417d9f-5e8c-491e-b513-41d8cc1f185e",
  "book_type": "in_progress",
  "privacy_settings": {"exclude_journal_ids": []}
}
```

Response:
- HTTP `201`
- Body (key fields):
```json
{
  "status": "failed",
  "error_message": "ReportLab is required to build Journey Book PDFs.",
  "error_code": "pdf_dependency_missing",
  "error_display": "PDF export is temporarily unavailable. You can view a sample and try again.",
  "can_preview_sample": true,
  "can_retry": true
}
```

Persisted model state:
- `JourneyBook.status = failed`
- `JourneyBook.error_message = "ReportLab is required to build Journey Book PDFs."`

Dependency evidence:
- Runtime check returned `reportlab_installed False` in this environment.

Follow-up actions on same failed book (`id=57911449-34dd-47a6-a9fb-69f5e12e99f1`):
- `GET /api/journeybook/{id}/preview/` -> `200` with sample payload (`source: generated_chapters`).
- `GET /api/journeybook/{id}/download/` -> `404` with `{"error": "Book not ready"}`.

Root-cause classification:
- **Technical error** (missing PDF dependency), not missing user data.

### B) Missing-data rejection reproduced (eligibility gate)

Request:
- Endpoint: `POST /api/journeybook/`
- Payload:
```json
{
  "goal_id": "5a77895a-f50e-465f-a816-fa9661ffe6f0",
  "book_type": "in_progress"
}
```

Response:
- HTTP `400`
- Body:
```json
{
  "book_type": [
    "In-progress journey book is not eligible for this goal/data window."
  ],
  "eligibility": {
    "can_generate_complete": "False",
    "can_generate_in_progress": "False",
    "can_choose_type": "False",
    "days_of_data": "1",
    "reason_blocked": "Come back after at least 7 days of journey data.",
    "goal_id": "5a77895a-f50e-465f-a816-fa9661ffe6f0",
    "goal_title": "Low Data Goal"
  }
}
```

Code evidence for this gate:
- Eligibility logic in `roadmap/journeybook/services/data_collector.py:29-66`
  - `< 7 days` -> blocked with `Come back after at least 7 days of journey data.`
- Serializer rejects in-progress generation when not eligible in `roadmap/journeybook/serializers.py:155-163`.

Root-cause classification:
- **Missing data** (insufficient days of journey data).

## 3) Exact failing request(s) tied to UI failure text

Primary failing request that drives the UI card state:
- `POST /api/journeybook/` returning a JourneyBook record with `status="failed"` and
  - `error_code="pdf_dependency_missing"`
  - `error_display="PDF export is temporarily unavailable. You can view a sample and try again."`

Where the UI string is sourced:
- Backend mapping: `roadmap/journeybook/serializers.py:95-108` (`_map_error`)
- Frontend display logic: `../roadmap-smart-planner/components/journey-book/BookCard.tsx:31-35,70`

## 4) Notes on non-root-cause environment issue observed during reproduction

- Initial local script call failed with `DisallowedHost: Invalid HTTP_HOST header: 'testserver'`.
- This was resolved by adding `testserver` to `ALLOWED_HOSTS` at runtime in the reproduction script.
- This is separate from Journey Book generation root causes.

## 5) Summary

- Journey Book implementation exists end-to-end (frontend + backend + PDF builder).
- Reproduced both failure classes with direct request/response evidence:
  - **Technical**: missing `reportlab` -> generation fails at PDF build stage.
  - **Missing data**: eligibility check blocks generation below 7 days.
- The specific UI state from your screenshot/message is reproducibly caused by the **technical dependency failure** path in this environment.

## 6) Troubleshooting Quick Checks

If Journey Book or PDF export fails again, check in this order:

1. Dependency check (PDF engine)
- Verify `reportlab` is importable in backend runtime.
- If missing, export may fail with `PDF_ENGINE_ERROR` or `pdf_dependency_missing`.

2. Export endpoint and payload
- Call `POST /api/journeybook/{id}/export/`.
- Confirm response fields:
  - `status`
  - `pdf_url`
  - `is_demo_pdf`
  - `error_type`
  - `fallback_available`

3. Book content readiness
- For real export, confirm book has non-empty metadata:
  - `chapter_count > 0`, `page_count > 0`, `word_count > 0`.
- Empty content triggers demo export path (`EMPTY_CONTENT`).

4. Data eligibility
- Verify `days_of_data >= 7` for in-progress generation eligibility.
- Insufficient data path should return/trigger `INSUFFICIENT_DATA` and demo fallback.

5. Frontend API mapping
- Ensure frontend `JourneyBook.EXPORT` points to `/api/journeybook/{id}/export/`.
- Confirm UI labels:
  - demo export -> `Download Demo PDF`
  - CTA -> `Generate real book`

6. File serving
- If `pdf_url` exists but download fails, verify backend file storage and `download` action access to `book.pdf_file`.
