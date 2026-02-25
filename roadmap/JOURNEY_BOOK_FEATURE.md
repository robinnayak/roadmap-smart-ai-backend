# JOURNEY_BOOK_FEATURE.md
# Roadmap Smart Planner — Journey Book Feature Specification
# Version: 1.0 | Status: Ready for Implementation

---

## 1. CONCEPT

A personalized, AI-generated memoir-style PDF documenting the user's transformation
from their journey start date to goal completion (or present day if in-progress).

Core principle every page must answer:
> "What did this cost me — and was it worth it?"

This is a STORY, not a data report. Tone is memoir, not analytics dashboard.

---

## 2. EXISTING INFRASTRUCTURE (Do Not Rebuild)

The following is already built in this project. Journey Book CONSUMES these,
it does not replace them:

- **Journal app** (`roadmap/journal/`) — JournalEntry model with sentiment_score,
  sentiment_label, tags, word frequencies, streak data. Journey Book reads from this.
- **Auth system** — existing JWT/session auth. Journey Book uses same pattern.
- **User/Profile** — existing User model. Journey Book adds no new user fields.

### What Journal data Journey Book needs:
- JournalEntry: entry_date, reflection_raw, struggle_raw, sentiment_score,
  sentiment_label, tags, total_word_count
- JournalStreak: current_streak, longest_streak, last_entry_date
- WordCloudAggregate: frequencies dict (word -> count)

If Journal app models are not available at import time, catch ImportError and
return empty list — never crash Journey Book due to missing Journal data.

---

## 3. DJANGO APP LOCATION

App already created at: `roadmap/journeybook/`

Do NOT run startapp again. Wire it into existing settings and urls only.

---

## 4. BOOK TYPE SELECTION LOGIC

```
User clicks "Generate My Journey Book" for a selected Goal
        │
        ▼
Does goal have status='completed' OR goal.deadline <= today?
        │
       YES ──────────────────────────────► Offer: Complete Book
        │                                   (also offer In-Progress as option)
        NO
        │
        ▼
Does user have >= 180 days of tracked data (journal entries or goal age)?
        │
       YES ──────────────────────────────► Offer BOTH types (user chooses)
        │
        NO
        │
        ▼
Does user have >= 7 days of data?
        │
       YES ──────────────────────────────► In-Progress only (auto, no choice)
        │
        NO
        └────────────────────────────────► Block: "Come back after 7 days"
```

Expose this logic via `GET /api/journeybook/eligibility/?goal_id=<uuid>`

---

## 5. BOOK STRUCTURES

### 5a. Complete Book (100–130 PDF pages equivalent)
- Past tense, fully reflective
- All chapters use real historical data
- 7 Chapters + 8 Motivational Pages

### 5b. In-Progress Book (60–90 PDF pages equivalent)
- Forward-looking and encouraging
- Chapters 1–3 use real data
- Chapters 4–5 use AI projections (clearly labeled "PROJECTION")
- 5 Motivational Pages

---

## 6. CHAPTER STRUCTURE (7 Chapters)

| # | Title | Data Source | Tone |
|---|-------|-------------|------|
| 1 | Who I Was — Day One | Real: profile, first journal, goal creation date | Reflective, honest |
| 2 | First 30 Days | Real: early journal entries, early habit data | Narrative, momentum |
| 3 | The Dip | Real: detected struggle period (see Algorithm A) | Raw, honest |
| 4 | The Turning Point | Real: first comeback after dip | Triumphant |
| 5 | The Progress | Real: measurable changes over time | Data-driven but human |
| 6 | The Moments | Real: curated journal highlights | Curated, intimate |
| 7 | Who I Became | Real (complete) / Projected (in-progress) | Celebratory / Aspirational |

For In-Progress books: Chapters 1–3 = real data, Chapters 4–5 only (skip 6–7 or use projection).

---

## 7. MOTIVATIONAL PAGES

### Complete Book (8 pages):
1. The Day You Didn't Quit
2. Before & After (stat + identity comparison)
3. Streak Wall Heatmap
4. The Invisible Wins
5. What You Learned About Yourself
6. The Three Hardest Days
7. Milestones Map
8. Letter to My Past Self

### In-Progress Book (5 pages):
1. The Day You Didn't Quit
2. Streak Wall Heatmap
3. The Invisible Wins
4. What You Learned About Yourself
5. Letter to My Past Self

---

## 8. IMAGE ASSETS (Generate Server-Side)

All images generated in Python. NO external URL dependencies at generation time.

| Image | Library | Source Data |
|-------|---------|-------------|
| Completion Rate Chart | matplotlib | Daily task/habit completion % over time |
| Sentiment Trend Chart | matplotlib | JournalEntry.sentiment_score over time |
| Streak Timeline Chart | matplotlib | Streak lengths as bar chart |
| Streak Heatmap Calendar | matplotlib | Gold=done, Gray=missed, Bronze=partial |
| Word Cloud Image | wordcloud library | WordCloudAggregate.frequencies (stopword filtered) |
| Milestone Timeline | matplotlib | Derived milestones with dates (see Section 10) |

Placeholder thematic images (no generation needed):
- sunrise.jpg → Chapter 1 / Start
- storm.jpg → Chapter 3 / Dip
- summit.jpg → Chapter 7 / Achievement
Store in: `roadmap/journeybook/static/journeybook/placeholders/`

---

## 9. KEY ALGORITHMS

### Algorithm A: Dip Period Detection
Primary: Find longest consecutive block of missed journal entries >= 3 days.
Fallback: Find 7-day window with lowest rolling average sentiment_score.
Output: { dip_start_date, dip_end_date, dip_type: 'missed_days'|'low_sentiment', severity: float }
Use in: Chapter 3, "The Three Hardest Days" motivational page.

### Algorithm B: Day You Didn't Quit
Find first journal entry date after a gap of >= 3 consecutive missed days.
If no 3-day gap: find first entry after any 2-day gap.
If no gap at all: use the date with lowest sentiment_score that still has an entry
(they showed up even when feeling bad).
Output: { comeback_date, days_missed_before, entry_snippet }

### Algorithm C: Three Hardest Days
Sort JournalEntry by sentiment_score ASC.
Take top 3 that have non-empty reflection_raw (at least 20 chars).
Ensure they are at least 7 days apart (no clustering).
Output: list of { date, sentiment_score, reflection_snippet }

### Algorithm D: Invisible Wins
Detect these patterns from data (heuristic):
- "Showed up low": entry exists AND sentiment_score < -0.2 (journaled despite feeling bad)
- "Streak rebuilt": current_streak recovered to >= 7 after dropping to 0
- "Consistent despite gap": completion rate >= 70% in week following a missed-days period
- "Volume surge": single week with word_count > 2x personal average
Each win gets a human-readable label. Return up to 12 wins.

### Algorithm E: Projections (In-Progress only)
Using last 30 days of data:
- completion_trend = linear regression slope of daily completion rate
- sentiment_trend = linear regression slope of daily sentiment_score
Project forward to goal.deadline:
- "At your current pace of X% completion, by [deadline] you will have..."
- Always frame positively even if trend is flat
Mark all projected content with is_projection=True in BookChapter.

### Algorithm F: Derived Milestones
Since no dedicated Milestone model exists, derive from data:
| Trigger | Label |
|---------|-------|
| First journal entry | "The First Step" |
| 7-day journal streak | "One Week In" |
| 30-day journal streak | "A Month of Discipline" |
| 100-day journal streak | "Century Mark" |
| First completed sub-goal | "First Win" |
| Journal entry count >= 50 | "50 Stories Written" |
| Average sentiment crosses 0.3 | "Turning the Corner" |
Store derived milestones in DerivedMilestone table (see models).

---

## 10. DATABASE MODELS

### JourneyBook (main record)
```python
id: UUIDField (primary key)
user: FK(User, CASCADE, related_name='journey_books')
goal: FK('goals.Goal', SET_NULL, null=True, related_name='journey_books')
  # Note: wrap in try/except if goals app not available
book_type: CharField choices=['complete', 'in_progress']
status: CharField choices=['queued', 'generating', 'ready', 'failed']
data_start_date: DateField
data_end_date: DateField
days_of_data: IntegerField
pdf_file: FileField(upload_to='journey_books/pdf/')
metadata: JSONField(default=dict)
  # keys: page_count, chapter_count, word_count, images_generated, dip_period, key_dates
privacy_settings: JSONField(default=dict)
  # keys: exclude_journal_ids (list), include_progress_photos (bool)
error_message: TextField(blank=True)
generation_started_at: DateTimeField(null=True)
generation_completed_at: DateTimeField(null=True)
created_at: DateTimeField(auto_now_add)
updated_at: DateTimeField(auto_now)

Indexes: [user, status], [user, goal], [created_at]
```

### BookChapter (cache + debug)
```python
id: UUIDField
journey_book: FK(JourneyBook, CASCADE, related_name='chapters')
chapter_number: IntegerField
chapter_title: CharField(max_length=200)
content: TextField
word_count: IntegerField(default=0)
is_projection: BooleanField(default=False)
ai_model_used: CharField(max_length=100, blank=True)
generation_time_seconds: FloatField(null=True)
created_at: DateTimeField(auto_now_add)

unique_together: [journey_book, chapter_number]
```

### BookAsset (generated images)
```python
id: UUIDField
journey_book: FK(JourneyBook, CASCADE, related_name='assets')
asset_type: CharField choices=[
  'completion_chart', 'sentiment_chart', 'streak_chart',
  'heatmap', 'wordcloud', 'milestone_timeline', 'placeholder_thematic'
]
file_path: CharField(max_length=500)
created_at: DateTimeField(auto_now_add)
```

### DerivedMilestone (computed, cached)
```python
id: UUIDField
user: FK(User, CASCADE, related_name='derived_milestones')
label: CharField(max_length=200)
trigger_type: CharField(max_length=100)
achieved_date: DateField
category: CharField choices=['discipline', 'career', 'health', 'personal', 'writing']
created_at: DateTimeField(auto_now_add)

unique_together: [user, trigger_type]
```

---

## 11. API ENDPOINTS

All endpoints require authentication. Use same auth pattern as rest of project.

```
POST   /api/journeybook/generate/              — Create generation request
GET    /api/journeybook/                        — List user's books (paginated)
GET    /api/journeybook/<uuid>/                 — Get book status + metadata
GET    /api/journeybook/<uuid>/download/        — Serve PDF file (auth-gated)
GET    /api/journeybook/eligibility/            — Check eligibility for a goal
         ?goal_id=<uuid>
DELETE /api/journeybook/<uuid>/                 — Delete a book record + file
```

### POST /api/journeybook/generate/ — Request body:
```json
{
  "goal_id": "uuid-string",
  "book_type": "complete | in_progress | auto",
  "privacy_settings": {
    "exclude_journal_ids": [],
    "include_progress_photos": false
  }
}
```

### GET /api/journeybook/<uuid>/ — Response:
```json
{
  "id": "uuid",
  "book_type": "complete",
  "status": "ready | generating | queued | failed",
  "days_of_data": 245,
  "metadata": {
    "page_count": 112,
    "chapter_count": 7,
    "word_count": 18400,
    "images_generated": 6
  },
  "download_url": "/api/journeybook/<uuid>/download/",
  "generated_at": "2026-02-25T10:30:00Z",
  "error_message": null
}
```

### Rate Limiting:
- Max 1 generation per user per 24 hours
- Return 429 with { "error": "Rate limit", "next_allowed_at": "ISO datetime" } if exceeded

---

## 12. PDF GENERATION APPROACH

Use **ReportLab** directly (NOT LibreOffice, NOT docx conversion).
ReportLab is pure Python, works on all platforms including Vercel/Railway/Render.

PDF structure:
1. Title Page
2. Dedication Page
3. Chapter 1–7 (each chapter starts on new page)
4. Motivational Pages (interspersed or appended)
5. Appendix: Goals summary table + Milestones list

Typography:
- Headings: Helvetica-Bold (ReportLab built-in)
- Body: Helvetica (ReportLab built-in)
- For serif look: embed a free serif TTF (e.g., Libre Baskerville from Google Fonts)
  Store in: roadmap/journeybook/static/journeybook/fonts/

Page size: A4 (595 x 842 points)
Margins: 72pt (1 inch) all sides

Image embedding:
- Generate each image to BytesIO
- Embed via ReportLab's drawImage / ImageReader
- Never write image to disk during generation (use BytesIO only)

---

## 13. AI TEXT GENERATION

If ANTHROPIC_API_KEY is in Django settings:
- Use claude-haiku-4-5 (cost-efficient for bulk chapter generation)
- Model string: read from settings.CLAUDE_MODEL, fallback to 'claude-haiku-4-5-20251001'
- Max tokens per chapter: 2000
- Max tokens per motivational page: 800
- Wrap in try/except — if AI call fails, fall back to template narrative

If ANTHROPIC_API_KEY is NOT in settings:
- Use template-based narrative generation (see Section 14)
- All hooks must be structured so AI can be swapped in later with no model changes

System prompt for all chapter generation:
```
You are writing a chapter for a deeply personal memoir about someone's
self-transformation journey. This is their real story, told in past tense
(or forward-looking for projected chapters). Write with warmth, honesty,
and specificity. Use the data facts provided. Never invent events that
aren't supported by the data. Write 600–900 words. Format as flowing
prose paragraphs — no bullet points, no headers within the chapter text.
```

---

## 14. TEMPLATE NARRATIVE FALLBACK

For each chapter, create a TemplateFallback class with:
- A string template using Python .format() with named placeholders
- Placeholders reference metrics dict keys only (never hardcoded values)
- Minimum 300 words per chapter
- Include a comment: # AI_UPGRADE_HOOK — replace this method with AI call

Example structure:
```python
class ChapterFallbacks:
    @staticmethod
    def chapter_1(metrics: dict) -> str:
        # AI_UPGRADE_HOOK
        return CHAPTER_1_TEMPLATE.format(
            name=metrics['profile']['name'],
            start_date=metrics['journey']['start_date'],
            goal_title=metrics['goal']['title'],
            ...
        )
```

---

## 15. PRIVACY ENFORCEMENT

privacy_settings.exclude_journal_ids must be enforced in DataCollector:
```python
def _get_journals_data(self):
    excluded = self.privacy_settings.get('exclude_journal_ids', [])
    qs = JournalEntry.objects.filter(user=self.user)
    if excluded:
        qs = qs.exclude(id__in=excluded)
    return list(qs.values(...))
```

Only owner can access their books — enforce in get_queryset:
```python
def get_queryset(self):
    return JourneyBook.objects.filter(user=self.request.user)
```

Download endpoint must call get_object() (which applies get_queryset filter)
before returning the file — never serve by file path directly.

---

## 16. FILE STRUCTURE TO CREATE

```
roadmap/journeybook/
├── __init__.py                    (exists)
├── models.py
├── serializers.py
├── views.py
├── urls.py
├── admin.py
├── tests.py
├── services/
│   ├── __init__.py
│   ├── data_collector.py          (collects all user data safely)
│   ├── metrics_calculator.py      (algorithms A–F)
│   ├── ai_generator.py            (Claude API + template fallback)
│   ├── image_generator.py         (matplotlib charts, heatmap, wordcloud)
│   └── pdf_builder.py             (ReportLab PDF assembly)
├── static/journeybook/
│   ├── fonts/
│   │   └── LibreBaskerville-Regular.ttf
│   └── placeholders/
│       ├── sunrise.jpg
│       ├── storm.jpg
│       └── summit.jpg
└── migrations/
    └── __init__.py                (exists)
```

---

## 17. FRONTEND ROUTES AND COMPONENTS

Route: `/journey-book` (or `/journeybook` — match existing route convention)

Pages:
- `/journey-book` — list of generated books + "Generate" CTA
- `/journey-book/generate` — goal selection + type selection modal (or inline)

Components to create in `components/journey-book/`:
- `JourneyBookList.tsx` — list with status badge + download button
- `GenerateModal.tsx` — goal picker + type selector (shows only eligible types)
- `EligibilityBadge.tsx` — shows "Complete available" or "In-Progress only"
- `GenerationStatus.tsx` — polling component (poll every 5s while status=generating)
- `BookCard.tsx` — individual book card: type, date range, page count, download

Status polling logic:
```typescript
// Poll every 5 seconds while status is 'generating' or 'queued'
// Stop polling when status becomes 'ready' or 'failed'
// Show elapsed time during generation
// Show error message if failed with a "Try Again" button
```

API endpoints to add to existing API config:
```typescript
JourneyBook: {
  LIST: '/api/journeybook/',
  GENERATE: '/api/journeybook/generate/',
  GET_ONE: (id: string) => `/api/journeybook/${id}/`,
  DOWNLOAD: (id: string) => `/api/journeybook/${id}/download/`,
  ELIGIBILITY: '/api/journeybook/eligibility/',
  DELETE: (id: string) => `/api/journeybook/${id}/`,
}
```

TypeScript types to add in `types/journeybook.ts`:
```typescript
export interface JourneyBook {
  id: string
  book_type: 'complete' | 'in_progress'
  status: 'queued' | 'generating' | 'ready' | 'failed'
  days_of_data: number
  data_start_date: string
  data_end_date: string
  metadata: {
    page_count: number
    chapter_count: number
    word_count: number
    images_generated: number
  }
  download_url: string | null
  generated_at: string | null
  error_message: string | null
  created_at: string
}

export interface BookEligibility {
  can_generate_complete: boolean
  can_generate_in_progress: boolean
  can_choose_type: boolean          // true if >= 180 days
  days_of_data: number
  reason_blocked: string | null     // if both false: explain why
  goal_id: string
  goal_title: string
}
```

---

## 18. BACKEND TESTS (Required)

Test file: `roadmap/journeybook/tests.py`

Write tests for:
1. `test_eligibility_less_than_7_days` — returns blocked
2. `test_eligibility_7_to_179_days` — in_progress only
3. `test_eligibility_180_plus_days` — both types available
4. `test_eligibility_completed_goal` — complete available regardless of days
5. `test_generate_creates_record` — POST /generate creates JourneyBook row with status=queued/generating
6. `test_generate_rate_limit` — second request within 24h returns 429
7. `test_download_requires_ownership` — user B cannot download user A's book
8. `test_download_returns_pdf` — status=ready returns PDF content-type
9. `test_download_not_ready_returns_404` — status=generating returns 404
10. `test_dip_detection_finds_gap` — given entries with 5-day gap, finds dip correctly
11. `test_dip_detection_fallback_sentiment` — no gap but low sentiment triggers dip
12. `test_derived_milestones_first_step` — first journal entry creates milestone
13. `test_derived_milestones_streak_7` — 7-day streak creates milestone
14. `test_privacy_excludes_journal_ids` — excluded journal not in book data
15. `test_delete_removes_file` — DELETE endpoint removes PDF file from storage
16. `test_book_chapter_saved_per_chapter` — after generation, BookChapter rows exist

Use Django TestCase + DRF APIClient. Mock Anthropic API in all tests.

---

## 19. IMPORTANT CONSTRAINTS

1. **Never crash if Journal data is unavailable** — always try/except ImportError on cross-app imports
2. **Never use LibreOffice** — use ReportLab only
3. **Never expose file paths directly** — all downloads through authenticated endpoint
4. **Never hardcode Claude model string** — use settings.CLAUDE_MODEL
5. **Always save BookChapter rows** — one per chapter, after AI generation
6. **Always enforce privacy_settings.exclude_journal_ids** in data collection
7. **Always mark projected content** — BookChapter.is_projection = True for chapters 4–5 in in-progress books
8. **Never write images to disk** — use BytesIO throughout image generation pipeline
9. **Rate limit enforced server-side** — not just frontend
10. **File cleanup on DELETE** — delete PDF file from storage when record is deleted

---

## 20. ACCEPTANCE CRITERIA

- [ ] User can click "Generate My Journey Book" for a goal and a JourneyBook record is created
- [ ] Book type selection follows the eligibility rules exactly
- [ ] PDF is generated with correct chapter count per book type
- [ ] At least 4 image types embedded in PDF (completion chart, sentiment chart, heatmap, word cloud)
- [ ] Download endpoint is auth-gated and returns actual PDF
- [ ] In-progress chapters 4–5 are clearly marked as projections
- [ ] BookChapter rows saved for every chapter (for debugging)
- [ ] DerivedMilestone rows computed from existing data
- [ ] Privacy exclusion of journal IDs works correctly
- [ ] Rate limiting blocks second generation within 24 hours
- [ ] All 16 backend tests pass
- [ ] Frontend shows book list, generation status polling, and download button
- [ ] DELETE removes both record and PDF file