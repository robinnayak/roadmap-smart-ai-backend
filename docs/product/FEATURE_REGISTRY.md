# Feature Registry

Date updated: 2026-02-26

## Journey Book
- Status: Active with fallback
- Backend:
  - Generation API: implemented
  - Preview fallback: implemented
  - Demo viewer fallback trigger support: implemented
- Frontend:
  - View Sample -> demo viewer: implemented
  - Try Again auto-demo fallback (insufficient/empty/known error): implemented

## Journey Book PDF Export
- Status: Active with demo export fallback
- Endpoint:
  - `POST /api/journeybook/{id}/export/`
- Response contract:
  - `status`, `pdf_url`, `demo_pdf_url`, `is_demo_pdf`, `error_type`, `fallback_available`
- Export behavior:
  - Ready + valid content -> real PDF
  - Failed/insufficient/empty -> demo PDF
  - PDF engine failure -> structured error, `fallback_available=true`

## Verification
- Backend tests:
  - ready -> real PDF export
  - insufficient data -> demo PDF export
  - PDF engine failure -> structured fallback-available error
- Frontend tests:
  - View Sample decision opens demo viewer
  - Try Again insufficient payload triggers demo fallback
  - Try Again empty content chooses demo fallback reason
