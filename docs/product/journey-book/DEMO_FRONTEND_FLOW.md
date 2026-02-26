# Journey Book Demo Frontend Flow

This documents the frontend integration for the new public demo preview endpoint.

## Goal

Allow users to open a full Book Viewer experience from demo data without requiring login for the preview request.

## UI Entry Point

On Journey Books page:

- Added button: `View Demo Book`
- Added trim selector: `5.5x8.5 | 6x9 (default) | 7x10`
- Added button: `Download Demo PDF` (header)
- Added subtle label: `Demo Preview - Example Transformation`

## Request Flow

1. User clicks `View Demo Book`.
2. Frontend calls `GET /journey-books/demo-preview/` via `journeyBookApi.demoPreview(trim_size)`.
3. No auth token is attached for this endpoint.
4. Response is mapped into the existing `JourneyBookContent` viewer schema.
5. Existing `BookViewerModal` opens with mapped content.
6. Viewer displays print metadata, including selected trim size.

## Demo PDF Download Flow

1. User picks trim size.
2. Frontend builds URL for `GET /journey-books/demo-preview/pdf/` with `book_type` + `trim_size`.
3. Frontend triggers download directly through browser navigation (`window.open`) without auth headers.
4. The same action is available in both page header and book viewer modal.

## Reuse Strategy

- Reused existing viewer UI (`BookViewerModal`) so demo and real viewing keep the same visual structure.
- No duplicate viewer component was introduced.
- Existing local `data/demo/journey_book_demo.json` remains as a client fallback only if API call fails.

## Safety / Separation

- Demo preview fetch is read-only and does not create/update Journey Book records.
- Demo PDF download is also read-only and does not create/update Journey Book records.
- Real generation/list/export logic remains unchanged.
- Demo preview and demo PDF are isolated to dedicated API helpers on the page layer.
