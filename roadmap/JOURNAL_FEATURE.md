# Journal Page Feature - Implementation Spec (Frontend + Backend) v2

## Goal
Implement a Journal Page that feels like writing in a beautiful personal journal (book-like UI), not a form. It must support daily entries with 4 fields, auto-save, AI auto-phrasing (raw -> polished), timezone-correct today, edit-lock policy, search/navigation with pagination, streak integration, word-cloud aggregation with stopword filtering, and offline recovery.

Project paths:
- Frontend: `D:\Earnings methods\delvery ready projects\roadmap-smart-planner1\roadmap-smart-planner`
- Backend:  `D:\Earnings methods\delvery ready projects\roadmap-smart-planner1\roadmap-smart-planner-backend\roadmap`

---

## Critical Policies (Must Implement)

### 1) Edit Window / Lock Policy (Server-Enforced)
Default policy:
- Entries are editable until end of the user's local day (23:59:59) for `entry_date`.
- After that moment, entry is locked forever (read-only).
- No unlock old entries in v1.

Implementation:
- JournalEntry must have `locked_at` (datetime, computed on create) and `is_locked` (derived, NOT stored) OR store `is_locked` boolean updated by server.
Recommended:
- Store `locked_at` and derive `is_locked = now_in_user_tz > locked_at`.

Rules:
- Backend must reject updates to locked entries with 403 and a clear error code.
- Frontend must also disable editing when locked, but backend is source of truth.

### 2) Timezone Handling (Single Source of Truth = Server)
- Store user timezone in profile/settings.
- Compute today and lock times using user timezone, not server timezone.

Implementation:
- Add `timezone` field to user profile/settings if missing.
  - Default: `Asia/Kathmandu` if not set.
- API should accept timezone in either:
  - Header: `X-User-Timezone: Asia/Kathmandu` (preferred), OR
  - Use stored profile timezone if header missing.
- Server computes:
  - `today_local_date`
  - `locked_at` = end of day for `entry_date` in user tz

---

## Data Model (Backend)

### New Model: JournalEntry
Fields:
- id (UUID)
- user (FK)
- entry_date (Date, unique per user+date)

Raw text:
- reflection_raw (Text, default "")
- struggle_raw (Text, default "")
- tomorrow_priority_raw (Text, default "")
- gratitude_raw (Text, default "")

Polished text (nullable):
- reflection_polished (Text, null=True, blank=True)
- struggle_polished (Text, null=True, blank=True)
- tomorrow_priority_polished (Text, null=True, blank=True)
- gratitude_polished (Text, null=True, blank=True)

Version choice:
- used_version (varchar; raw|polished|mixed; default raw)

Enrichment:
- sentiment_label (varchar; positive/neutral/negative/mixed, default neutral)
- sentiment_score (float; -1..1, default 0)
- tags (JSON array, default [])
- total_word_count (int, default 0)
- field_word_counts (JSON dict, default {})

Locking:
- locked_at (datetime)  # end-of-day in user TZ at creation time

Timestamps:
- created_at, updated_at

Constraints:
- UniqueConstraint(user, entry_date)
Indexes:
- index on (user, entry_date)
- index on (user, updated_at)

---

## Tomorrow's Priority -> Routine Connection (v1 Scope)
v1 decision: Do NOT auto-create a routine task.
- Store `tomorrow_priority_*` in JournalEntry.
- Routine page may read it later (future integration). No side effects in v1.

---

## Sentiment + Auto-Phrasing (AI Strategy)

### AI Provider Priority
- If the project already has an AI provider wired (Claude/OpenAI/other), use it for:
  1) Auto-phrasing
  2) Sentiment + tags
- If no remote AI provider is configured, fallback:
  - Auto-phrasing: rule-based cleanup (capitalization, punctuation, remove filler)
  - Sentiment: keyword heuristic + simple score mapping

Optional local:
- If Ollama exists in repo, allow config flag to use it (only if already working).

### Auto-Phrasing Fallback Rule
- Always attempt AI first if configured.
- If AI fails (timeout, key missing), fallback to rule-based.

---

## Rate Limiting (Must)
Auto-phrase endpoint must be rate-limited:
- Implement per-user daily quota using DRF throttling or custom counter.
Default quotas:
- Free: 20 requests/day
- Pro: 200 requests/day (not unlimited yet; safer)
- Return 429 with clear code when exceeded.

If billing tiers are not implemented yet:
- Treat everyone as Free for now, but keep tier logic ready.

---

## Word Cloud Aggregation (Must Be Useful)
- Filter stop words before counting.
- Use a static stopword list in code (no heavy NLP dependency required).
- Normalize words:
  - lowercase
  - strip punctuation
  - ignore < 3 chars
  - optionally basic stemming NOT required in v1

Storage approach:
- Recommended: `WordCloudAggregate` per user:
  - user (OneToOne)
  - frequencies (JSON map word->count)
  - updated_at
- Update incrementally on entry save:
  - subtract old counts + add new counts (delta method), or recompute from all entries if delta is complex (acceptable for MVP).

---

## Offline / Network Failure UX (Frontend Must)
Implement local draft buffering with recovery:
- On every keystroke, save current draft to `localStorage` under key:
  - `journal:draft:{YYYY-MM-DD}`
- When loading a date:
  - Fetch server entry
  - Compare updated timestamps or a local `draft_saved_at`
  - If local draft is newer than server, show banner:
    - Recover unsaved draft? [Recover] [Discard]
- On successful autosave, clear local draft for that date.

---

## Backend API (DRF)

### Auth
All endpoints require authenticated user.

### Common Rules
- Backend must compute `is_locked` and include it in responses.
- Any write to locked entry returns 403.

### Endpoints
1) GET/PUT Entry by date (Upsert)
- `GET /journal/entries/?date=YYYY-MM-DD`
  - Returns entry if exists, else empty shape for that date.
  - Includes `is_locked`, `locked_at`, `entry_date`, enrichment fields.
- `PUT /journal/entries/?date=YYYY-MM-DD`
  - Upserts entry if not locked.
  - Recompute enrichment (word counts, sentiment, tags).
  - Update streak + word cloud aggregate.
  - Returns updated entry.

2) Auto-Phrase
- `POST /journal/auto-phrase/`
  - Body: { field: reflection|struggle|tomorrow_priority|gratitude, text: ... }
  - Returns: { polished: ..., confidence: 0..1 }
  - Rate limited per user/day.

3) Search (Paginated)
- `GET /journal/search/?q=...&field=all|reflection|struggle|tomorrow_priority|gratitude&sentiment=...&from=YYYY-MM-DD&to=YYYY-MM-DD&page=1&page_size=20`
  - Returns paginated results with:
    - date, sentiment_label, tags, snippet
  Snippet rules:
  - 150 characters max
  - if `q` provided, highlight matches:
    - wrap matches with `<mark>...</mark>` in snippet (safe plain text)
  Full-text:
  - Prefer Postgres search if available; else icontains fallback.

4) Dates with entries (Paginated)
- `GET /journal/dates/?page=1&page_size=60`
  - Returns list of dates that have entries for calendar highlights.

5) Aggregates
- `GET /journal/stats/`
  - Returns streak + total_entries + longest_streak.
- `GET /journal/wordcloud/?limit=50`
  - Returns top words (word,count) excluding stopwords.

### Serializers
- JournalEntrySerializer (read/write)
- JournalSearchResultSerializer (snippet + metadata)
- AutoPhraseSerializer
- Pagination classes

### Permissions
- Only owner access.

### Tests (Backend Must)
- Create entry, update entry
- Unique per user+date
- Lock enforcement (cannot update after locked_at)
- Timezone correctness (use X-User-Timezone header)
- Auto-phrase rate limiting
- Search pagination + filters
- Dates pagination

---

## Frontend (Next.js)

### Route
- `/journal`

### UI Components
- JournalHeader (date display, streak chip)
- JournalPaper (paper texture + ruled lines)
- JournalSection (prompt + writing area + word count)
- PolishedPreview (raw + polished toggle, apply polished)
- JournalCalendarPicker (jump to date; highlights entry dates)
- JournalSearchPanel (keyword + field + sentiment + date range)
- JournalShelfView (stacked pages list)

### Behaviors
- Default date = server-correct today (or compute with profile tz).
- Autosave:
  - debounce 800-1200ms
  - show subtle Saving... / Saved
- Locked:
  - if is_locked true: read-only inputs, hide polish action.
- Offline draft buffer:
  - localStorage write-behind + recovery banner.
- Search results:
  - show snippet (render <mark> as highlight safely).
- Pagination controls for search and dates.

### API Layer
Add `API_ENDPOINTS.Journal`:
- ENTRY_BY_DATE (GET/PUT)
- AUTO_PHRASE (POST)
- SEARCH (GET paginated)
- DATES (GET paginated)
- STATS (GET)
- WORDCLOUD (GET)

### Styling
- Tailwind CSS
- Serif font (next/font if already used)
- Paper + ruled lines via CSS backgrounds

---

## Integration Notes
- Journal streak should be exposed for dashboard usage if dashboard already has streak UI.
- Keep enrichment fields stable for future Journey Book generation.

---

## Acceptance Criteria
- [ ] Today is correct per user timezone.
- [ ] Entries lock at end of local day and are server-enforced.
- [ ] Autosave works and survives refresh.
- [ ] Offline recovery banner works.
- [ ] Auto-phrase rate limits.
- [ ] Word cloud excludes stopwords.
- [ ] Search returns highlighted snippet and paginates.
- [ ] Dates endpoint paginates and supports calendar highlighting.
