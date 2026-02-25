# CODEX_JOURNEY_BOOK_PROMPT.md
# Structured Codex Agent Prompt — Journey Book Feature
# Feed these phases IN ORDER. Complete each phase before starting the next.
# Reference JOURNEY_BOOK_FEATURE.md at any point for full spec details.

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 0 — ORIENTATION (Read-only. Do NOT write any code.)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
You are a senior full-stack developer implementing a Journey Book feature on an
existing Django + Next.js project. A Django app has already been created at:

  roadmap/journeybook/

Do NOT run startapp again. The app folder already exists.

Before writing any code, audit the project and report the following.
Do NOT modify any files during this phase.

PROJECT PATHS:
  Backend:  D:\Earnings methods\delvery ready projects\roadmap-smart-planner1\roadmap-smart-planner-backend\roadmap
  Frontend: D:\Earnings methods\delvery ready projects\roadmap-smart-planner1\roadmap-smart-planner

SPEC FILE: JOURNEY_BOOK_FEATURE.md (in project root or provided alongside this prompt)

─── BACKEND AUDIT ───────────────────────────────────────

1. Show contents of: roadmap/settings.py
   Focus on: INSTALLED_APPS, AUTH_USER_MODEL, DATABASES, MEDIA_ROOT,
   MEDIA_URL, REST_FRAMEWORK, and any API keys (ANTHROPIC_API_KEY etc.)

2. Show contents of: roadmap/urls.py (main URL config)

3. List all Django app directories under roadmap/
   For each app, list the model class names defined in its models.py

4. Show the User model (custom or django.contrib.auth.models.User?)
   Show UserProfile model if it exists.

5. Show the Journal app models (roadmap/journal/models.py or similar)
   I need to know: exact model name, field names for entry_date,
   sentiment_score, tags, word frequencies, streak model name and fields.
   If journal app does not exist, say so clearly.

6. Show the Goals app models — exact model name, fields for:
   status, deadline, category, title, user FK field name.
   If goals app does not exist, say so clearly.

7. Check requirements.txt or Pipfile for these packages:
   - anthropic
   - reportlab
   - matplotlib
   - wordcloud
   - Pillow
   - django-rest-framework
   Report which are present and which need to be installed.

8. Show an example API view from any existing app to understand:
   - Response wrapper format (does it use { data: ..., success: ... } or raw?)
   - Auth pattern used (IsAuthenticated? Custom permission class?)
   - Pagination class used (if any)

─── FRONTEND AUDIT ──────────────────────────────────────

9. Show package.json dependencies section.

10. Show the API config/constants file (wherever API endpoints are defined).
    Usually: lib/api.ts, utils/api.ts, constants/api.ts, or similar.

11. Show how a typical API call is made — show one example of a GET and
    one example of a POST from an existing feature (e.g., goals or journal).
    I need to see: how auth tokens are attached, base URL, error handling.

12. Show the routing setup: is this Next.js App Router (app/) or Pages Router (pages/)?

13. List existing components in components/ folder (just names, 2 levels deep).

14. Show an example of an existing private page component (e.g., dashboard or goals page).

─── REPORT FORMAT ───────────────────────────────────────

After completing the audit, report:

FINDINGS SUMMARY:
- AUTH_USER_MODEL: [value]
- Journal app exists: [yes/no] | Model name: [name] | Key fields: [list]
- Goals app exists: [yes/no] | Model name: [name] | Key fields: [list]
- ANTHROPIC_API_KEY in settings: [yes/no]
- Missing pip packages: [list]
- API response wrapper format: [describe]
- Next.js router type: [app/pages]
- Auth header format: [Bearer token / Cookie / other]

Do not write any code until Phase 1 is explicitly started.
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 1 — BACKEND: MODELS + MIGRATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
Using the audit findings from Phase 0, implement the Journey Book models.

BACKEND PATH: D:\Earnings methods\delvery ready projects\roadmap-smart-planner1\roadmap-smart-planner-backend\roadmap

─── STEP 1: Install missing packages ────────────────────

If any of these are missing from requirements.txt, install them and add to requirements.txt:
  pip install reportlab matplotlib wordcloud Pillow anthropic

─── STEP 2: Add journeybook to INSTALLED_APPS ───────────

In roadmap/settings.py, add 'journeybook' to INSTALLED_APPS if not present.

─── STEP 3: Write roadmap/journeybook/models.py ─────────

Write four models exactly as specified in JOURNEY_BOOK_FEATURE.md Section 10.

CRITICAL rules:
- Use UUIDField primary keys (uuid.uuid4, editable=False)
- The `goal` FK must be wrapped: import Goals model inside try/except ImportError
  If import fails, goal field should still work as a plain UUID store:
  ```python
  try:
      from goals.models import Goal  # adjust app name from audit
      goal_fk = models.ForeignKey(Goal, on_delete=models.SET_NULL, null=True, blank=True)
  except ImportError:
      goal_fk = models.UUIDField(null=True, blank=True)
  ```
  Actually, the cleaner approach: use a string reference in FK:
  goal = models.ForeignKey(
      'goals.Goal',   # replace 'goals' with actual app name from audit
      on_delete=models.SET_NULL,
      null=True, blank=True,
      related_name='journey_books'
  )
  Django resolves string FKs lazily — this won't crash if goals app is installed.

- JourneyBook.status choices: 'queued', 'generating', 'ready', 'failed'
- JourneyBook.book_type choices: 'complete', 'in_progress'
- BookChapter.is_projection: BooleanField(default=False) — REQUIRED
- BookAsset.asset_type choices: see spec Section 10
- DerivedMilestone has unique_together [user, trigger_type]

Add these helper methods to JourneyBook:
  def mark_generating(self): sets status='generating', generation_started_at=now(), saves
  def mark_ready(self, metadata): sets status='ready', metadata=metadata, generation_completed_at=now(), saves
  def mark_failed(self, error): sets status='failed', error_message=error, generation_completed_at=now(), saves

  @property
  def generation_duration_seconds(self):
      if self.generation_started_at and self.generation_completed_at:
          return (self.generation_completed_at - self.generation_started_at).total_seconds()
      return None

─── STEP 4: Write roadmap/journeybook/admin.py ──────────

Register all four models. For JourneyBook admin:
- list_display: user, book_type, status, days_of_data, created_at
- list_filter: book_type, status
- search_fields: user__email
- readonly_fields: generation_started_at, generation_completed_at, metadata

─── STEP 5: Run migrations ──────────────────────────────

cd roadmap
python manage.py makemigrations journeybook
python manage.py migrate

Report migration output. If any errors, fix them before proceeding.
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 2 — BACKEND: SERVICES LAYER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
Implement the five service modules inside roadmap/journeybook/services/

Create the folder and an empty __init__.py first.

─── FILE 1: services/data_collector.py ──────────────────

Class: DataCollector(user, goal_id=None, privacy_settings=None)

Method: collect_all_data() -> dict
Returns a dict with these keys:
  {
    'profile': {...},
    'goal': {...},          # the specific goal this book is about
    'journals': [...],      # list of journal entry dicts
    'streaks': {...},
    'word_frequencies': {}, # from WordCloudAggregate if available
    'derived_milestones': [...],
  }

Method: check_eligibility(goal_id) -> dict
Implements the decision tree from JOURNEY_BOOK_FEATURE.md Section 4.
Returns:
  {
    'can_generate_complete': bool,
    'can_generate_in_progress': bool,
    'can_choose_type': bool,        # True if >= 180 days
    'days_of_data': int,
    'reason_blocked': str or None,
    'goal_id': str,
    'goal_title': str,
  }

CRITICAL: All cross-app imports must be wrapped in try/except:
  def _get_journals(self):
      try:
          # Use exact model name and field names from Phase 0 audit
          from journal.models import JournalEntry
          excluded = (self.privacy_settings or {}).get('exclude_journal_ids', [])
          qs = JournalEntry.objects.filter(user=self.user)
          if excluded:
              qs = qs.exclude(id__in=excluded)
          qs = qs.order_by('entry_date')
          return list(qs.values(
              'id', 'entry_date', 'reflection_raw', 'struggle_raw',
              'sentiment_score', 'sentiment_label', 'tags', 'total_word_count'
          ))
      except (ImportError, Exception) as e:
          return []  # Journal not available — degrade gracefully

  def _get_streaks(self):
      try:
          from journal.models import JournalStreak  # adjust model name from audit
          streak = JournalStreak.objects.get(user=self.user)
          return {
              'current_streak': streak.current_streak,
              'longest_streak': streak.longest_streak,
              'last_entry_date': streak.last_entry_date,
          }
      except (ImportError, Exception):
          return {'current_streak': 0, 'longest_streak': 0, 'last_entry_date': None}

  def _get_word_frequencies(self):
      try:
          from journal.models import WordCloudAggregate  # adjust from audit
          agg = WordCloudAggregate.objects.get(user=self.user)
          return agg.frequencies
      except (ImportError, Exception):
          return {}

  def _get_goal(self, goal_id):
      if not goal_id:
          return {}
      try:
          from goals.models import Goal  # adjust from audit
          goal = Goal.objects.get(id=goal_id, user=self.user)
          return {
              'id': str(goal.id),
              'title': goal.title,
              'category': getattr(goal, 'category', 'personal'),
              'status': goal.status,
              'deadline': goal.deadline,
              'created_at': goal.created_at.date() if hasattr(goal, 'created_at') else None,
          }
      except (ImportError, Exception):
          return {}

─── FILE 2: services/metrics_calculator.py ──────────────

Class: MetricsCalculator(collected_data: dict)

Method: calculate_all() -> dict
Runs all algorithms and returns:
  {
    'journey_overview': {...},
    'dip': {...},             # Algorithm A result
    'comeback': {...},         # Algorithm B result
    'hardest_days': [...],    # Algorithm C result (3 items)
    'invisible_wins': [...],  # Algorithm D result
    'derived_milestones': [...], # Algorithm F result
    'behavioral_patterns': {...},
    'completion_trend': float,   # slope (Algorithm E)
    'sentiment_trend': float,    # slope (Algorithm E)
    'projections': {...},        # Algorithm E result (in-progress only)
  }

Implement each algorithm from JOURNEY_BOOK_FEATURE.md Section 9.

Algorithm A — dip_detection(journals: list) -> dict:
  # 1. Find all consecutive gaps >= 3 days in entry_date sequence
  # 2. Find the longest gap: {'dip_start_date', 'dip_end_date', 'days_missed', 'dip_type': 'missed_days'}
  # 3. If no gap >= 3: compute 7-day rolling average sentiment
  #    Find window with lowest average
  #    Return {'dip_start_date', ..., 'dip_type': 'low_sentiment', 'severity': float}
  # 4. If no journals at all: return {'dip_start_date': None, 'dip_type': 'none'}

Algorithm B — comeback_detection(journals: list, dip: dict) -> dict:
  # Find first entry_date AFTER dip_end_date
  # If no dip: find first entry after any 2-day gap
  # If no gap: find entry with lowest sentiment that still has content
  # Return {'comeback_date', 'days_missed_before', 'entry_snippet': first 150 chars}

Algorithm C — hardest_days(journals: list) -> list[dict]:
  # Sort by sentiment_score ASC
  # Filter: only entries where len(reflection_raw) >= 20
  # Pick 3, ensuring each is >= 7 days apart from others
  # Return [{'date', 'sentiment_score', 'reflection_snippet'}]

Algorithm D — invisible_wins(journals: list, streaks: dict) -> list[dict]:
  # Detect patterns described in spec Section 9 Algorithm D
  # Return up to 12 wins as [{'label': str, 'date': date, 'detail': str}]

Algorithm E — projections(journals: list, goal: dict) -> dict:
  # Only called for in_progress books
  # Use last 30 entries for trend
  # Simple linear regression on sentiment_score over time index
  # Simple linear regression on word_count over time index
  # Return {'completion_projection': str, 'sentiment_trajectory': str,
  #         'projected_completion_date': date or None}
  # Implement linear regression manually (no scipy): 
  #   slope = (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x^2) - sum(x)^2)

Algorithm F — derive_milestones(journals: list, goal: dict, streaks: dict) -> list[dict]:
  # Use trigger table from spec Section 9 Algorithm F
  # Check each trigger against data
  # Create/update DerivedMilestone rows in DB
  # Return list of achieved milestones

─── FILE 3: services/image_generator.py ─────────────────

Class: ImageGenerator(metrics: dict)

All methods return BytesIO objects (never write to disk).

Method: generate_completion_chart() -> BytesIO
  # Line chart: x=dates, y=daily completion rate (% of journals with positive sentiment)
  # matplotlib, figsize=(8,4), color='#4F7942', serif style
  # Title: "Your Consistency Over Time"

Method: generate_sentiment_chart() -> BytesIO
  # Line chart: x=dates, y=sentiment_score
  # Color gradient: negative=red, positive=green
  # Add horizontal line at y=0
  # Title: "Your Emotional Journey"

Method: generate_streak_chart() -> BytesIO
  # Bar chart of streak lengths over time
  # Color: gold (#FFD700) for bars
  # Title: "Streak Milestones"

Method: generate_heatmap() -> BytesIO
  # Calendar heatmap: rows=weeks, columns=days of week (Mon-Sun)
  # Color: gold if entry exists, gray if no entry
  # Title: "Your Journey Calendar"
  # Use matplotlib patches to draw the grid

Method: generate_wordcloud(frequencies: dict) -> BytesIO
  # If wordcloud library available:
  #   from wordcloud import WordCloud, STOPWORDS
  #   wc = WordCloud(width=800, height=400, background_color='white',
  #                  stopwords=STOPWORDS, max_words=100)
  #   wc.generate_from_frequencies(frequencies)
  # If wordcloud not available:
  #   Draw top 20 words as text with font sizes proportional to frequency using matplotlib
  # Return BytesIO of PNG

Method: generate_milestone_timeline(milestones: list) -> BytesIO
  # Vertical timeline: each milestone as a dot + label + date
  # matplotlib, vertical line down center, dots on alternating sides
  # Title: "Milestones Achieved"

─── FILE 4: services/ai_generator.py ────────────────────

Class: AIGenerator()

SYSTEM_PROMPT = """You are writing a chapter for a deeply personal memoir about
someone's self-transformation journey. Write with warmth, honesty, and
specificity. Use the data facts provided. Never invent events not supported
by the data. Write 600–900 words as flowing prose paragraphs — no bullet
points, no headers within the chapter text."""

Method: generate_chapter(chapter_config: dict, metrics: dict, book_type: str) -> str:
  # Build user message with context from metrics
  # If settings.ANTHROPIC_API_KEY exists:
  #   model = getattr(settings, 'CLAUDE_MODEL', 'claude-haiku-4-5-20251001')
  #   Call Anthropic API, return text
  # Else:
  #   Return ChapterFallbacks.get(chapter_config['id'], metrics)

Method: generate_motivational_page(page_type: str, metrics: dict) -> str:
  # Same pattern as generate_chapter but shorter (300-500 words)
  # page_type maps to specific prompts (see spec Section 13)
  # Fallback: MotivationalFallbacks.get(page_type, metrics)

Class: ChapterFallbacks:
  TEMPLATES = {
    'ch1': """On {start_date}, {name} made a decision...
              [300+ word template about starting the journey]
              # AI_UPGRADE_HOOK""",
    'ch2': """The first thirty days were...""",
    # ... one per chapter
  }
  
  @classmethod
  def get(cls, chapter_id: str, metrics: dict) -> str:
      template = cls.TEMPLATES.get(chapter_id, cls.TEMPLATES['ch1'])
      return template.format(**cls._flatten_metrics(metrics))
  
  @classmethod
  def _flatten_metrics(cls, metrics: dict) -> dict:
      # Flatten nested metrics dict for .format() substitution
      # Include safe defaults for all keys

─── FILE 5: services/pdf_builder.py ─────────────────────

Class: PDFBuilder(user_data: dict, metrics: dict, book_type: str)

Use ReportLab exclusively. No LibreOffice. No docx.

Key imports:
  from reportlab.lib.pagesizes import A4
  from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
  from reportlab.lib.units import inch, cm
  from reportlab.lib.colors import HexColor, black, white
  from reportlab.platypus import (
      SimpleDocTemplate, Paragraph, Spacer, PageBreak,
      Image as RLImage, Table, TableStyle, HRFlowable
  )
  from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
  from io import BytesIO

Method: build(chapters: list[str], motivational_pages: list[str],
              images: dict[str, BytesIO]) -> BytesIO:
  # 1. Create BytesIO buffer
  # 2. Create SimpleDocTemplate with A4, 1-inch margins
  # 3. Define styles (see below)
  # 4. Build story list: title page, dedication, chapters, motivational pages, appendix
  # 5. doc.build(story)
  # 6. Return buffer

Styles to define:
  - TitleStyle: Helvetica-Bold, 36pt, centered, dark brown #3D2B1F
  - SubtitleStyle: Helvetica, 18pt, centered, gray #666666
  - ChapterHeadingStyle: Helvetica-Bold, 24pt, left, dark brown
  - BodyStyle: Helvetica, 12pt, justified, line spacing 16pt, space after 10pt
  - QuoteStyle: Helvetica-Oblique, 12pt, left indent 0.5in, gray #555555
  - ProjectionStyle: same as body but with italic and a "PROJECTION" label prefix
  - PageNumberStyle: Helvetica, 9pt, centered, gray

Title page content:
  - Top third: large decorative spacer
  - Center: "The Journey" in TitleStyle
  - Below: "{name}'s Transformation" in SubtitleStyle
  - Below: "{start_date} — {end_date}" in SubtitleStyle
  - If in_progress: add "(In Progress)" note in small gray text
  - If sunrise.jpg placeholder exists in static folder, embed it centered

Chapter page layout:
  - PageBreak before each chapter
  - Chapter number in small caps: "CHAPTER ONE" (gray, small)
  - Chapter title in ChapterHeadingStyle
  - HRFlowable divider line
  - Body paragraphs parsed from chapter text string
  - If chapter has images dict entry, embed image centered after chapter title

Embedding images:
  def _embed_image(self, image_bytesio: BytesIO, width_inches: float = 5.0) -> RLImage:
      image_bytesio.seek(0)
      img = RLImage(image_bytesio, width=width_inches*inch,
                    height=(width_inches*0.5)*inch)
      return img

Projection pages:
  - Add gray box at top: "⚠ PROJECTION — Based on your current trajectory"
  - Then body text

Appendix:
  - Goals summary table (3 cols: Goal, Status, Deadline)
  - Milestones list (bullet list with dates)

After all steps are complete, confirm:
  - Each service file created and has no import errors
  - Run: python -c "from journeybook.services import data_collector, metrics_calculator, image_generator, ai_generator, pdf_builder; print('All services importable')"
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 3 — BACKEND: SERIALIZERS + VIEWS + URLS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
Implement serializers, views, and URL routing for the Journey Book API.
Match EXACTLY the response format used elsewhere in this project (from Phase 0 audit).

─── STEP 1: roadmap/journeybook/serializers.py ──────────

JourneyBookSerializer (read):
  Fields: id, book_type, book_type_display, status, status_display,
          days_of_data, data_start_date, data_end_date, metadata,
          download_url (SerializerMethodField), error_message,
          generation_duration_seconds, created_at, updated_at
  
  get_download_url: return request.build_absolute_uri(
    reverse('journeybook:download', args=[obj.id])
  ) if obj.status == 'ready' else None

JourneyBookGenerateSerializer (write/validation):
  Fields:
    goal_id: UUIDField(required=False, allow_null=True)
    book_type: ChoiceField(['complete', 'in_progress', 'auto'])
    privacy_settings: DictField(required=False, default=dict)
  
  validate(data):
    - If goal_id provided, verify goal belongs to request.user
    - Check eligibility via DataCollector.check_eligibility(goal_id)
    - If book_type='complete' but not eligible: raise ValidationError
    - If book_type='auto': resolve to 'complete' or 'in_progress' based on eligibility
    - Check rate limit: if user has a book with status in ['queued','generating']
      OR last 'ready' book was created < 24h ago: raise ValidationError with
      { 'error': 'Rate limit', 'next_allowed_at': <ISO datetime> }
    - Return validated data

BookEligibilitySerializer (read):
  Fields: can_generate_complete, can_generate_in_progress, can_choose_type,
          days_of_data, reason_blocked, goal_id, goal_title

─── STEP 2: roadmap/journeybook/views.py ────────────────

Use same base classes / mixins as existing project views (from audit).

Class: JourneyBookViewSet(ModelViewSet or GenericViewSet — match project style)
  permission_classes: [IsAuthenticated]  (or project's custom auth class)
  
  def get_queryset(self):
      return JourneyBook.objects.filter(user=self.request.user)
  
  def get_serializer_class(self):
      if self.action == 'create':
          return JourneyBookGenerateSerializer
      return JourneyBookSerializer
  
  def create(self, request):
      # 1. Validate with JourneyBookGenerateSerializer
      # 2. Collect data: DataCollector(user, goal_id, privacy_settings).collect_all_data()
      # 3. Calculate metrics: MetricsCalculator(data).calculate_all()
      # 4. Create JourneyBook record with status='queued'
      # 5. Call _generate_sync(book, data, metrics) — see below
      # 6. Return serialized book (status will be 'ready' or 'failed')
  
  def destroy(self, request, pk=None):
      book = self.get_object()
      # Delete PDF file from storage before deleting record
      if book.pdf_file:
          book.pdf_file.delete(save=False)
      book.delete()
      return Response(status=204)
  
  @action(detail=False, methods=['get'])
  def eligibility(self, request):
      goal_id = request.query_params.get('goal_id')
      collector = DataCollector(request.user, goal_id=goal_id)
      data = collector.check_eligibility(goal_id)
      serializer = BookEligibilitySerializer(data)
      return Response(serializer.data)
  
  @action(detail=True, methods=['get'])
  def download(self, request, pk=None):
      book = self.get_object()
      if book.status != 'ready' or not book.pdf_file:
          return Response({'error': 'Book not ready'}, status=404)
      response = FileResponse(
          book.pdf_file.open('rb'),
          content_type='application/pdf'
      )
      response['Content-Disposition'] = (
          f'attachment; filename="journey_book_{str(book.id)[:8]}.pdf"'
      )
      return response
  
  def _generate_sync(self, book, data, metrics):
      book.mark_generating()
      try:
          ai_gen = AIGenerator()
          img_gen = ImageGenerator(metrics)
          
          structure = self._get_structure(book.book_type)
          
          # Generate chapters + save BookChapter rows
          chapters_text = []
          for i, ch_config in enumerate(structure['chapters'], 1):
              start = time.time()
              text = ai_gen.generate_chapter(ch_config, metrics, book.book_type)
              duration = time.time() - start
              BookChapter.objects.create(
                  journey_book=book,
                  chapter_number=i,
                  chapter_title=ch_config['title'],
                  content=text,
                  word_count=len(text.split()),
                  is_projection=ch_config.get('is_projection', False),
                  ai_model_used=getattr(settings, 'CLAUDE_MODEL', 'template'),
                  generation_time_seconds=duration,
              )
              chapters_text.append(text)
          
          # Generate motivational pages text
          motivational_text = []
          for page_type in structure['motivational_pages']:
              text = ai_gen.generate_motivational_page(page_type, metrics)
              motivational_text.append(text)
          
          # Generate images
          images = {}
          try:
              images['completion'] = img_gen.generate_completion_chart()
              images['sentiment'] = img_gen.generate_sentiment_chart()
              images['heatmap'] = img_gen.generate_heatmap()
              if data.get('word_frequencies'):
                  images['wordcloud'] = img_gen.generate_wordcloud(data['word_frequencies'])
              images['milestone'] = img_gen.generate_milestone_timeline(
                  metrics.get('derived_milestones', [])
              )
          except Exception as e:
              # Images are non-critical — log and continue
              print(f"Image generation partial failure: {e}")
          
          # Build PDF
          pdf_builder = PDFBuilder(data, metrics, book.book_type)
          pdf_bytes = pdf_builder.build(chapters_text, motivational_text, images)
          
          # Save PDF to model
          filename = f"journey_book_{book.user.id}_{book.id}.pdf"
          book.pdf_file.save(filename, ContentFile(pdf_bytes.getvalue()), save=False)
          
          # Save assets
          for asset_type, _ in images.items():
              BookAsset.objects.create(
                  journey_book=book,
                  asset_type=asset_type,
                  file_path=f"generated/{asset_type}_{book.id}.png"
              )
          
          # Derive and save milestones
          for m in metrics.get('derived_milestones', []):
              DerivedMilestone.objects.get_or_create(
                  user=book.user,
                  trigger_type=m['trigger_type'],
                  defaults={
                      'label': m['label'],
                      'achieved_date': m['achieved_date'],
                      'category': m.get('category', 'personal'),
                  }
              )
          
          book.mark_ready({
              'page_count': len(chapters_text) * 5 + len(motivational_text) * 2 + 5,
              'chapter_count': len(chapters_text),
              'word_count': sum(len(c.split()) for c in chapters_text),
              'images_generated': len(images),
          })
      
      except Exception as e:
          book.mark_failed(str(e))
          raise
  
  def _get_structure(self, book_type: str) -> dict:
      if book_type == 'complete':
          return {
              'chapters': [
                  {'id': 'ch1', 'title': 'Who I Was — Day One', 'is_projection': False},
                  {'id': 'ch2', 'title': 'The First 30 Days', 'is_projection': False},
                  {'id': 'ch3', 'title': 'The Dip', 'is_projection': False},
                  {'id': 'ch4', 'title': 'The Turning Point', 'is_projection': False},
                  {'id': 'ch5', 'title': 'The Progress', 'is_projection': False},
                  {'id': 'ch6', 'title': 'The Moments', 'is_projection': False},
                  {'id': 'ch7', 'title': 'Who I Became', 'is_projection': False},
              ],
              'motivational_pages': [
                  'the_day_you_didnt_quit', 'before_after', 'streak_heatmap',
                  'invisible_wins', 'what_you_learned', 'three_hardest_days',
                  'milestones_map', 'letter_to_past_self',
              ]
          }
      else:  # in_progress
          return {
              'chapters': [
                  {'id': 'ch1', 'title': 'Who I Was — Day One', 'is_projection': False},
                  {'id': 'ch2', 'title': 'Your Journey So Far', 'is_projection': False},
                  {'id': 'ch3', 'title': 'The Challenges', 'is_projection': False},
                  {'id': 'ch4', 'title': 'If You Keep Going', 'is_projection': True},
                  {'id': 'ch5', 'title': 'The Future You', 'is_projection': True},
              ],
              'motivational_pages': [
                  'the_day_you_didnt_quit', 'streak_heatmap',
                  'invisible_wins', 'what_you_learned', 'letter_to_past_self',
              ]
          }

─── STEP 3: roadmap/journeybook/urls.py ─────────────────

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'journeybook'

router = DefaultRouter()
router.register(r'', views.JourneyBookViewSet, basename='journeybook')

urlpatterns = [
    path('', include(router.urls)),
]

# This gives us:
# GET/POST  /api/journeybook/
# GET/DELETE /api/journeybook/<uuid>/
# GET       /api/journeybook/<uuid>/download/
# GET       /api/journeybook/eligibility/

─── STEP 4: Wire into main urls.py ──────────────────────

Add to roadmap/urls.py:
  path('api/journeybook/', include('journeybook.urls', namespace='journeybook')),

─── STEP 5: Verify endpoints ────────────────────────────

Start the server and verify these return expected responses (even if data is empty):
  GET /api/journeybook/ → 200 with empty list
  GET /api/journeybook/eligibility/ → 200 with eligibility data
  POST /api/journeybook/ → validation errors if no data sent (expected)

Report results.
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 4 — BACKEND: TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
Write all backend tests in roadmap/journeybook/tests.py

Use Django TestCase and DRF APIClient.
Mock ALL external services: Anthropic API, matplotlib, wordcloud library.

─── TEST SETUP ──────────────────────────────────────────

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import date, timedelta
from django.utils import timezone
import uuid

from journeybook.models import JourneyBook, BookChapter, DerivedMilestone
from journeybook.services.metrics_calculator import MetricsCalculator

User = get_user_model()

class JourneyBookTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otheruser', email='other@example.com', password='testpass123'
        )
        self.client.force_authenticate(user=self.user)

─── TESTS TO WRITE ──────────────────────────────────────

Write each of these 16 tests:

1. test_eligibility_less_than_7_days
   Mock DataCollector to return 5 days_of_data.
   GET /api/journeybook/eligibility/?goal_id=<uuid>
   Assert: can_generate_in_progress=False, reason_blocked is not None.

2. test_eligibility_7_to_179_days
   Mock 90 days. Assert: can_generate_in_progress=True, can_generate_complete=False,
   can_choose_type=False.

3. test_eligibility_180_plus_days
   Mock 200 days. Assert: can_choose_type=True, both can_generate_* = True.

4. test_eligibility_completed_goal
   Mock 30 days BUT goal status='completed'. Assert: can_generate_complete=True.

5. test_generate_creates_record
   Mock entire generation pipeline. POST /api/journeybook/ with book_type='in_progress'.
   Assert: JourneyBook row created, response status 201.

6. test_generate_rate_limit
   Create existing JourneyBook with status='ready', created_at=now()-30min.
   POST /api/journeybook/ again. Assert: 429 response.

7. test_generate_rate_limit_resets_after_24h
   Create existing book with created_at=now()-25h. POST again.
   Assert: 201 (allowed).

8. test_download_requires_ownership
   Create JourneyBook owned by other_user with status='ready'.
   self.client (authenticated as user) GET /api/journeybook/<other_book_id>/download/
   Assert: 404 (not found, because get_queryset filters by user).

9. test_download_returns_pdf
   Create JourneyBook for self.user with status='ready', mock pdf_file.
   GET /api/journeybook/<id>/download/
   Assert: 200, Content-Type=application/pdf.

10. test_download_not_ready_returns_404
    Create JourneyBook with status='generating'.
    GET /api/journeybook/<id>/download/
    Assert: 404.

11. test_dip_detection_finds_gap
    Create journal data with entries on days 1-5, then gap days 6-12, then day 13.
    Call MetricsCalculator({'journals': [...]}).calculate_all()
    Assert: dip['dip_type'] == 'missed_days', dip['days_missed'] >= 6.

12. test_dip_detection_fallback_sentiment
    Create journal data with no gaps but low sentiment_score (-0.8) for one week.
    Assert: dip['dip_type'] == 'low_sentiment'.

13. test_derived_milestones_first_step
    Provide journal data with at least 1 entry.
    Call metrics_calculator.calculate_all()
    Assert: at least one milestone with trigger_type='first_journal_entry' in result.

14. test_derived_milestones_streak_7
    Provide streak data with longest_streak=7.
    Assert: milestone with trigger_type='streak_7' in result.

15. test_privacy_excludes_journal_ids
    Create two journal entries. Pass exclude_journal_ids=[entry_1.id] in privacy_settings.
    Call DataCollector(user, privacy_settings=...).collect_all_data()
    Assert: returned journals list has length 1 (excluded one is gone).
    Note: Mock JournalEntry import if journal app not yet fully wired.

16. test_book_chapter_saved_per_chapter
    Mock AI generator and PDF builder. POST /api/journeybook/ with in_progress.
    Assert: BookChapter.objects.filter(journey_book=book).count() == 5 (in_progress has 5 chapters).

─── RUN TESTS ───────────────────────────────────────────

cd roadmap
python manage.py test journeybook --verbosity=2

Report: number passed, number failed, any errors.
Fix any failures before moving to Phase 5.
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 5 — FRONTEND IMPLEMENTATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
Implement the Journey Book frontend. Match ALL existing project conventions
(component patterns, API call patterns, auth headers — from Phase 0 audit).

FRONTEND PATH: D:\Earnings methods\delvery ready projects\roadmap-smart-planner1\roadmap-smart-planner

─── STEP 1: Add TypeScript types ────────────────────────

Create: types/journeybook.ts (or add to existing types file — match project convention)

export type BookStatus = 'queued' | 'generating' | 'ready' | 'failed'
export type BookType = 'complete' | 'in_progress'

export interface JourneyBook {
  id: string
  book_type: BookType
  book_type_display: string
  status: BookStatus
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
  error_message: string | null
  generation_duration_seconds: number | null
  created_at: string
  updated_at: string
}

export interface BookEligibility {
  can_generate_complete: boolean
  can_generate_in_progress: boolean
  can_choose_type: boolean
  days_of_data: number
  reason_blocked: string | null
  goal_id: string | null
  goal_title: string | null
}

export interface GenerateBookPayload {
  goal_id?: string
  book_type: 'complete' | 'in_progress' | 'auto'
  privacy_settings?: {
    exclude_journal_ids: string[]
    include_progress_photos: boolean
  }
}

─── STEP 2: Add API endpoint constants ──────────────────

In the existing API constants file (found in Phase 0 audit), add:

JourneyBook: {
  LIST: '/api/journeybook/',
  GENERATE: '/api/journeybook/',           // POST to list endpoint
  GET_ONE: (id: string) => `/api/journeybook/${id}/`,
  DOWNLOAD: (id: string) => `/api/journeybook/${id}/download/`,
  ELIGIBILITY: '/api/journeybook/eligibility/',
  DELETE: (id: string) => `/api/journeybook/${id}/`,
}

─── STEP 3: Create components ───────────────────────────

Create folder: components/journey-book/
(Use existing component folder structure from audit — match naming style)

─── Component: BookCard.tsx ─────────────────────────────

Props:
  book: JourneyBook
  onDelete: (id: string) => void

Display:
- Book type badge: "Complete Journey" (green) or "In Progress" (blue)
- Status badge:
    queued → gray "Queued"
    generating → yellow pulsing "Generating..."
    ready → green "Ready"
    failed → red "Failed"
- Stats row: "{days_of_data} days · {metadata.chapter_count} chapters · {metadata.page_count} pages"
- Date range: "{data_start_date} → {data_end_date}"
- Word count: "{metadata.word_count.toLocaleString()} words written"
- Download button (only if status='ready'): primary button, links to download_url
- Delete button: ghost/icon button, confirm before delete
- If status='failed': show error_message in a small red text block with "Try Again" link

Styling: warm card aesthetic — cream/parchment background (#FDF6E3),
dark brown text (#3D2B1F), gold accents (#C9A84C).
Use serif font if available in the project's font setup.

─── Component: GenerateModal.tsx ────────────────────────

Props:
  isOpen: boolean
  onClose: () => void
  onGenerated: (book: JourneyBook) => void

State:
  step: 'goal-select' | 'type-select' | 'generating' | 'done'
  selectedGoalId: string | null
  eligibility: BookEligibility | null
  selectedType: BookType | null
  isLoading: boolean
  error: string | null

Step 1 — Goal Select:
  - Fetch user's goals from existing goals API endpoint
  - Show as clickable cards or dropdown
  - "No specific goal" option (book about overall journey)
  - On select: fetch eligibility for that goal_id
  - Show eligibility info: days of data, what's available

Step 2 — Type Select:
  - Only show if can_choose_type=true (180+ days)
  - Two cards:
    "Complete Journey" — past tense, all real data, 100-130 pages
    "In Progress" — forward-looking, projections, 60-90 pages
  - If only one type available: skip this step, auto-select

Step 3 — Generating:
  - Show after POST /api/journeybook/ with status=201
  - Loading animation: animated book pages or progress indicator
  - Text: "We're crafting your story... this takes 30-60 seconds"
  - Poll GET /api/journeybook/<id>/ every 5 seconds
  - Stop polling when status='ready' or 'failed'

Step 4 — Done:
  - If ready: "Your Journey Book is ready!" + Download button
  - If failed: error message + "Try Again" button

─── Component: GenerationStatus.tsx ─────────────────────

Props:
  bookId: string
  onStatusChange: (status: BookStatus, book: JourneyBook) => void

Hook: useJourneyBookPolling(bookId, enabled)
  - Polls GET /api/journeybook/<id>/ every 5000ms
  - Stops when status is 'ready' or 'failed'
  - Returns { book, isPolling, error }

Display during polling:
  - Animated spinner or pulsing dots
  - Elapsed time counter
  - Friendly messages cycling every 10s:
    ["Collecting your journal entries...",
     "Analyzing your transformation patterns...",
     "Writing your story with AI...",
     "Building your PDF...",
     "Almost done..."]

─── Component: EligibilityBadge.tsx ─────────────────────

Props: eligibility: BookEligibility

Display:
  - Green badge: "Complete Book Available ✓" if can_generate_complete
  - Blue badge: "In Progress Available" if can_generate_in_progress
  - Gray: "Not enough data — {reason_blocked}" if neither
  - Small text: "{days_of_data} days of journey data"

─── STEP 4: Create Journey Book page ────────────────────

Create: app/journey-book/page.tsx (or pages/journey-book.tsx — match router from audit)

Page layout:
  Header section:
    - Title: "Your Journey Books" (serif, large)
    - Subtitle: "Personalized memoirs of your transformation"
    - "Generate New Book" button (primary, top right)
  
  Empty state (no books yet):
    - Illustration or icon (book with sparkle)
    - Text: "Your first Journey Book is waiting to be written."
    - Subtitle: "Need at least 7 days of journal entries to generate."
    - "Generate Your Story" button

  Books list:
    - Grid of BookCard components
    - Most recent first
    - Skeleton loading state while fetching

  GenerateModal: rendered conditionally, controlled by isModalOpen state

Data fetching:
  - On mount: GET /api/journeybook/ to load books list
  - Use existing data fetching pattern from project (SWR, React Query, useEffect — match project)

─── STEP 5: Add Journey Book to navigation ──────────────

Find the existing sidebar/navbar component.
Add a link to /journey-book.
Icon suggestion: 📖 or a book SVG icon.
Label: "Journey Book"
Position: After "Journal" in the nav hierarchy.

─── STEP 6: Final checks ────────────────────────────────

1. Run the frontend dev server and navigate to /journey-book
2. Verify: page loads without errors
3. Verify: "Generate New Book" button opens modal
4. Verify: goal selection and eligibility fetch work
5. Verify: generation POST fires and polling begins
6. Verify: BookCard shows correct status badges
7. Verify: Download button triggers file download

Report any console errors or issues found.
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 6 — INTEGRATION + FINAL VERIFICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
Final integration checks and cleanup.

─── STEP 1: End-to-end smoke test ───────────────────────

With both backend and frontend running:

1. Login as a test user
2. Navigate to /journey-book
3. Click "Generate New Book"
4. Select a goal (or "overall journey")
5. Confirm eligibility is fetched and displayed
6. Select book type (if eligible for both)
7. Click "Generate"
8. Verify polling starts and status updates appear
9. Wait for generation to complete (or mock complete status)
10. Click Download
11. Verify PDF opens/downloads correctly
12. Verify BookCard shows page count, chapter count, word count
13. Navigate away and back — verify book persists in list
14. Test Delete — verify book disappears from list

─── STEP 2: Run all backend tests ───────────────────────

python manage.py test journeybook --verbosity=2

All 16 tests must pass. Fix any failures.

─── STEP 3: Check for issues ────────────────────────────

Verify these constraints from JOURNEY_BOOK_FEATURE.md Section 19:
[ ] Cross-app imports all wrapped in try/except
[ ] No LibreOffice usage anywhere in codebase
[ ] Download endpoint uses get_object() (ownership enforced)
[ ] Claude model string comes from settings, not hardcoded
[ ] BookChapter rows created for every chapter after generation
[ ] privacy_settings.exclude_journal_ids enforced in data_collector
[ ] BookChapter.is_projection=True for projected chapters
[ ] Images never written to disk (BytesIO only)
[ ] Rate limit enforced in serializer validate()
[ ] PDF file deleted from storage on record DELETE

Report: which are confirmed, which need fixing.

─── STEP 4: Add placeholder static assets ───────────────

Create placeholder images if they don't exist:
  roadmap/journeybook/static/journeybook/placeholders/

For each placeholder (sunrise.jpg, storm.jpg, summit.jpg):
  Create a simple colored rectangle using Pillow as placeholder:

  from PIL import Image as PILImage, ImageDraw
  # sunrise: warm orange gradient rectangle
  img = PILImage.new('RGB', (800, 400), color=(255, 180, 100))
  draw = ImageDraw.Draw(img)
  draw.text((20, 20), "Journey Start", fill=(80, 40, 0))
  img.save('sunrise.jpg')

  # storm: dark blue-gray rectangle
  # summit: bright white with gold

─── STEP 5: Add font file ───────────────────────────────

Download Libre Baskerville Regular (free Google Font, OFL license):
  https://fonts.google.com/specimen/Libre+Baskerville

Save to: roadmap/journeybook/static/journeybook/fonts/LibreBaskerville-Regular.ttf

Update pdf_builder.py to use this font if available:
  from django.contrib.staticfiles import finders
  font_path = finders.find('journeybook/fonts/LibreBaskerville-Regular.ttf')
  if font_path:
      pdfmetrics.registerFont(TTFont('LibreBaskerville', font_path))
      body_font = 'LibreBaskerville'
  else:
      body_font = 'Helvetica'  # fallback

─── STEP 6: Final report ────────────────────────────────

Provide a summary:
  - All files created (list them)
  - All tests passing (show count)
  - Any known limitations or TODOs for future improvement
  - Instructions for enabling async generation with Celery when ready
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# QUICK REFERENCE — ISSUES FIXED IN THIS IMPLEMENTATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The following issues from the original code review are fixed here:

1.  ✅ Missing goal FK                  → Added with string reference ('goals.Goal')
2.  ✅ 180-day rule missing             → Added can_choose_type to eligibility
3.  ✅ Brittle cross-app imports        → All wrapped in try/except ImportError
4.  ✅ LibreOffice PDF conversion       → Replaced with ReportLab (pure Python)
5.  ✅ Double-save file bug             → Single save via pdf_file.save()
6.  ✅ No image generation              → Full image_generator.py service
7.  ✅ No download endpoint             → @action download() on ViewSet
8.  ✅ Zero backend tests               → 16 required tests specified
9.  ✅ Chapters not saved to DB         → BookChapter created per chapter in _generate_sync
10. ✅ privacy_settings ignored         → Enforced in DataCollector._get_journals()
11. ✅ No rate limiting                 → Enforced in serializer validate()
12. ✅ Hardcoded model string           → settings.CLAUDE_MODEL with fallback
13. ✅ is_projection not tracked        → BookChapter.is_projection field added
14. ✅ Word cloud dependency on Journal → Graceful fallback if not available
15. ✅ No file cleanup on delete        → destroy() deletes PDF before record
16. ✅ No DerivedMilestone system       → Algorithm F + DerivedMilestone model