# =============================================================================
# roadmap/ai/models.py  (AIProcessingJob - relevant fixes shown)
# =============================================================================
#
# KEY FIXES:
#  - job_type choices now include 'situation_analysis' matching what services use
#  - status choices are all lowercase and consistently used everywhere
#  - 'row_data' renamed to 'input_data' (the actual field that exists on the model)
#
# JOB_TYPE_CHOICES (replace the existing tuple):
#
#   JOB_TYPE_CHOICES = [
#       ('situation_analysis', 'Analyze Current Situation'),   # <-- was missing
#       ('goal_generation', 'Generate Goals & Roadmap'),
#       ('goal_attributes', 'Extract Goal Attributes'),
#       ('milestone_generation', 'Generate Milestones'),
#       ('task_generation', 'Generate Daily Tasks'),
#       ('habit_suggestion', 'Suggest Habits'),
#       ('progress_analysis', 'Analyze Progress'),
#       ('motivation_generation', 'Generate Motivation'),
#   ]
#
#   JOB_STATUS_CHOICES = [
#       ('pending', 'Pending'),       # <-- always lowercase, use these exact strings
#       ('processing', 'Processing'),
#       ('completed', 'Completed'),
#       ('failed', 'Failed'),
#       ('cancelled', 'Cancelled'),
#   ]
#

import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class UserCurrentSituationGoal(models.Model):
    """Structured output extracted from AI for user situation & goals."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user_personal_details = models.OneToOneField(
        "authentication.UserPersonalDetails",
        on_delete=models.CASCADE,
        related_name="current_situation_goal",
        null=True,
        blank=True,
    )

    ai_processing_job = models.OneToOneField(
        "ai.AIProcessingJob",
        on_delete=models.CASCADE,
        related_name="current_situation_goal",
    )

    # Full AI output (source of truth)
    current_situation = models.JSONField()

    # Structured & queryable fields
    current_role = models.CharField(max_length=255, blank=True, null=True)
    age = models.IntegerField(blank=True, null=True)
    key_skills = models.JSONField(blank=True, null=True)
    main_goals = models.JSONField(blank=True, null=True)
    time_availability = models.CharField(max_length=255, blank=True, null=True)
    constraints = models.JSONField(blank=True, null=True)
    priority_areas = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Situation & Goals | User {self.ai_processing_job.user_id}"


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

CATEGORY_CHOICES = [
    ("financial", "Financial"),
    ("career", "Career"),
    ("health", "Health"),
    ("personal", "Personal"),
]

PRIORITY_CHOICES = [
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
]

# ---------------------------------------------------------------------------
# 2. Goal
#    A top-level life goal the user wants to achieve.
#    Can span multiple life areas (e.g. "Build SaaS" = career + financial).
# ---------------------------------------------------------------------------


class Goal(models.Model):
    """
        Multi-dimensional goals that can impact multiple life areas
        Example: "Build Trading Bot SaaS" affects career, finance, and personal
    growth
    """


    STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("paused", "Paused"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.CASCADE, related_name="goals"
    )

    # Goals Details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    why_it_matters = models.TextField(
        help_text="Why this goal is important - shown to user for motivation"
    )
    # key_skills = models.JSONField(
    #     blank=True, null=True
    # )  # goal specific key skills if already have

    primary_category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    # categories = models.JSONField(
    #     default=list,
    #     blank=True,
    #     help_text="""
    #     List of categories this goal belongs to. 
    #     Example: ["financial", "career", "personal"]
    #     """,
    # )
    impact_dimensions = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        Store how this goal affects different life areas:
        {
            'financial': {'weight': 0.8, 'target': 'Monthly revenue $10k',
'current': 3500},
            'career': {'weight': 0.9, 'target': 'Portfolio + Senior Dev
skills'},
            'health': {'weight': 0.3, 'target': 'Better work-life balance'},
            'personal': {'weight': 0.6, 'target': 'Entrepreneurship
confidence'}
        }
        """,
    )

    # Tags for flexibility filtering

    # tags = models.JSONField(
    #     default=list,
    #     blank=True,
    #     null=True,
    #     help_text="['side-business', 'passive-income', 'python', 'ai']",
    # )
    
    
    # Priority & Status
    
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="not_started"
    )
    # Timeline
    start_date = models.DateField(default=timezone.localdate)
    target_date = models.DateField(null=True, blank=True)
    # actual_completion_date = models.DateField(null=True, blank=True)
    # Progress
    progress_percentage = models.IntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    # AI Generated Flags
    is_ai_generated = models.BooleanField(default=False)
    ai_feasibility_score = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="AI-calculated feasibility score (0.0 to 1.0)",
    )
    
    
    ai_generation_context = models.TextField(
        blank=True, help_text="Context/reasoning behind AI-generated goal"
    )

    ai_reasoning = models.TextField(
        blank=True,
        help_text="Why the AI generated or scored this goal the way it did.",
    )

    # User Modification Tracking
    is_user_modified = models.BooleanField(
        default=False, help_text="True if user edited AI-generated goal"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "goals"
        ordering = ["-priority", "target_date", "created_at"]
        indexes = [
            models.Index(fields=["user", "primary_category"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "target_date"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_primary_category_display()})"
    
    def save(self, *args, **kwargs):
        # Guarantee primary_category is never empty
        if not self.primary_category and self.impact_dimensions:
            self.primary_category = next(iter(self.impact_dimensions), "personal")
        super().save(*args, **kwargs)

    @property
    def days_remaining(self) -> int | None:
        """Days until target_date. Negative means overdue."""
        if self.target_date and self.status != "completed":
            return (self.target_date - timezone.localdate()).days
        return None

    @property
    def is_overdue(self) -> bool:
        if self.target_date and self.status not in ("completed", "cancelled"):
            return timezone.localdate() > self.target_date
        return False

    def update_progress(self):
        """Recalculate progress from milestones and bubble it up."""
        milestones = self.milestones.all()
        if not milestones.exists():
            return
        completed = milestones.filter(status="completed").count()
        self.progress_percentage = int((completed / milestones.count()) * 100)
        if self.progress_percentage == 100:
            self.status = "completed"
        elif self.progress_percentage > 0:
            self.status = "in_progress"
        self.save(update_fields=["progress_percentage", "status", "updated_at"])

# ---------------------------------------------------------------------------
# 3. GoalAttributes
#    Domain-specific data for a goal, stored as typed JSONFields.
#    Kept separate so Goal stays lean and queryable.
#
#    Each JSONField is nullable — only populate what's relevant to the goal.
# ---------------------------------------------------------------------------

class GoalAttributes(models.Model):
    """
    Flexible, domain-specific detail attached to a Goal.

    Why JSONField per domain instead of one big `data` field?
      - Allows partial updates (PATCH financial_data only).
      - Keeps the intent clear for the AI when generating or updating.
      - Easier to validate per domain in serializers.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    goal = models.OneToOneField(
        Goal, on_delete=models.CASCADE, related_name="attributes"
    )

    # Ai processing jobs for fetching goal attribute such as financial, career, and so on (Task: Fetch user text prompt to JSON format)

    # ai_processing_job = models.OneToOneField(
    #     "ai.AIProcessingJob",
    #     on_delete=models.CASCADE,
    #     related_name="goal_attributes",
    #     null=True,
    #     blank=True,
    # )
    # =====
    # response in JSON Format which we will use to auto save after or before user input
    # =====
    # Financial Attributes (when goal has financial dimension)

    financial_data = models.JSONField(
        null=True,
        blank=True,
        help_text="""
        {
            'target_amount': 50000,
            'current_amount': 15000,
            'currency': 'USD',
            'monthly_target': 5000,
            'income_sources': ['salary', 'freelance', 'passive'],
            'savings_rate': 0.3,
            'investment_plan': 'Index funds',
            'break_even_month': 6
        }
        """,
    )

    # Career Attributes (when goal has career dimension)
    career_data = models.JSONField(
        null=True,
        blank=True,
        help_text="""
        {
            'target_role': 'Senior Developer',
            'target_company': 'FAANG',
            'current_role': 'Mid-level Dev',
            'skills_required': ['Python', 'AWS', 'Docker', 'System Design'],
            'skills_current': ['Python', 'Django'],
            'certifications_needed': ['AWS Solutions Architect'],
            'networking_events_target': 12,
            'portfolio_projects': ['Trading Bot', 'AI SaaS'],
            'resume_updates_needed': true
        }
        """,
    )

    # Health Attributes (when goal has health dimension)
    health_data = models.JSONField(
        null=True,
        blank=True,
        help_text="""
        {
            'start_weight_kg': 85,
            'target_weight_kg': 75,
            'current_weight_kg': 80,
            'start_body_fat_percent': 20,
            'target_body_fat_percent': 12,
            'current_body_fat_percent': 16,
            'workout_frequency_per_week': 5,
            'target_sleep_hours': 8,
            'nutrition_plan': 'High protein, calorie deficit',
            'measurements': {
                'chest_cm': 100,
                'waist_cm': 85,
                'arms_cm': 35
            }
        }
        """,
    )

    # Personal Development Attribures
    personal_data = models.JSONField(
        null=True,
        blank=True,
        help_text="""
        {
            'books_target': 24,
            'books_read': 8,
            'current_reading': ['Atomic Habits'],
            'relationships_to_strengthen': ['family', 'mentors'],
            'hobbies': ['guitar', 'photography'],
            'experiences_target': ['travel to Japan', 'learn diving'],
            'confidence_level_current': 6,
            'confidence_level_target': 9,
            'public_speaking_events': 5
        }
        """,
    )

    # Skill/Education Attributes
    # skill_data = models.JSONField(
    #     null=True,
    #     blank=True,
    #     help_text="""
    #     {
    #         'skill_name': 'Machine Learning',
    #         'current_level': 'Intermediate',
    #         'target_level': 'Advanced',
    #         'courses': ['Coursera ML', 'Fast.ai'],
    #         'courses_completed': 1,
    #         'practice_hours_target': 200,
    #         'practice_hours_current': 120,
    #         'projects_completed': 3,
    #         'certification_target': 'TensorFlow Developer'
    #     }
    #     """,
    # )

    # Custom attributes for any other type
    # custom_data = models.JSONField(
    #     null=True,
    #     blank=True,
    #     help_text="Any other custom attributes specific to this goal",
    # )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Attributes for {self.goal.title}"


# ===============================================================
# IMPROVED GOAL HIERARCHY MODELS
# ===============================================================
# Flow: Goal → Milestone (Monthly) → SubGoal (Weekly) → Task (Daily)
#
# Example:
# Goal: "Prepare for ML Interview by June 2026"
#   ├── Milestone 1: "Master Python Fundamentals" (Jan 2026)
#   │   ├── SubGoal: "Week 1: Data Structures" (Jan 1-7)
#   │   │   ├── Task: "Study Lists & Tuples - 2 hours" (Day 1)
#   │   │   ├── Task: "Practice 5 LeetCode Easy problems" (Day 1)
#   │   │   └── Task: "Review dictionaries & sets" (Day 2)
#   │   └── SubGoal: "Week 2: Algorithms Basics" (Jan 8-14)
#   │       ├── Task: "Learn Big O notation" (Day 8)
#   │       └── Task: "Practice sorting algorithms" (Day 9)
#   └── Milestone 2: "Master Linear Algebra" (Feb 2026)
#       └── SubGoal: "Week 1: Vectors & Matrices" (Feb 1-7)
#           └── Task: "Khan Academy: Matrix operations" (Day 1)
# ===============================================================


# ---------------------------------------------------------------------------
# 4. Milestone  (monthly / phase level)
#    Breaks a Goal into concrete phases shown on the Timeline page.
# ---------------------------------------------------------------------------


class Milestone(models.Model):
    """
    Monthly or phase-based milestones that break down the main goal.

    Example for "ML Interview Prep":
    - Milestone 1: "Master Python Fundamentals" (January 2026)
    - Milestone 2: "Learn Linear Algebra & Statistics" (February 2026)
    - Milestone 3: "Study ML Algorithms" (March 2026)
    - Milestone 4: "Deep Learning & Neural Networks" (April 2026)
    - Milestone 5: "System Design & Mock Interviews" (May 2026)
    - Milestone 6: "Final Interview Preparation" (June 2026)
    ....
    """

    STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("blocked", "Blocked"),
    ]

    # PRIORITY_CHOICES = [
    #     ("high", "High"),
    #     ("medium", "Medium"),
    #     ("low", "Low"),
    # ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="milestones")

    # Milestone Details
    title = models.CharField(
        max_length=255, help_text="Example: 'Master Python Fundamentals (January 2026)'"
    )
    description = models.TextField(
        blank=True,
        help_text="What you'll achieve: 'Learn data structures, algorithms, OOP concepts'",
    )
    success_criteria = models.TextField(
        blank=True,
        help_text="Example: 'Complete 50 LeetCode problems, build 2 Python projects, pass Python assessment'",
    )

    # Priority & Status
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="not_started"
    )

    # Progress (0–100); updated by update_progress()
    progress_percentage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Auto-calculated from subgoals",
    )

    # Timeline
    # month_year = models.CharField(
    #     max_length=20, blank=True, help_text="Example: 'January 2026' or 'Q1 2026'"
    # )
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(
        null=True, blank=True, help_text="Example: January 31, 2026"
    )
    completed_date = models.DateField(null=True, blank=True)
    # estimated_duration_days = models.IntegerField(
    #     null=True,
    #     blank=True,
    #     default=30,
    #     help_text="Typically 30 days for monthly milestones",
    # )

    # Ordering
    display_order = models.IntegerField(
        default=0, help_text="1 for January, 2 for February, etc."
    )
    # is_required = models.BooleanField(
    #     default=True, help_text="Some milestones might be optional based on progress"
    # )

    # Dependencies
    # depends_on = models.ManyToManyField(
    #     "self",
    #     symmetrical=False,
    #     blank=True,
    #     related_name="unlocks",
    #     help_text="Prerequisites: Must complete Python before ML Algorithms",
    # )

    # AI Generated
    is_ai_generated = models.BooleanField(default=True)
    ai_reasoning = models.TextField(
        blank=True,
        help_text="AI: 'Python fundamentals are essential foundation for ML interviews'",
    )

    # User Modification
    # is_user_modified = models.BooleanField(default=False)
    # is_user_added = models.BooleanField(default=False)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["goal", "display_order"]
        indexes = [
            models.Index(fields=["goal", "status"]),
            models.Index(fields=["goal", "target_date"]),
        ]

    def __str__(self):
        return f"{self.goal.title} → {self.title}"

    def update_progress(self):
        """Recalculate from subgoals, then cascade up to the parent Goal."""
        subgoals = self.subgoals.all()
        if not subgoals.exists():
            return
        completed = subgoals.filter(status="completed").count()
        self.progress_percentage = int((completed / subgoals.count()) * 100)
        if self.progress_percentage == 100:
            self.status = "completed"
            self.completed_date = timezone.localdate()
        elif self.progress_percentage > 0:
            self.status = "in_progress"
        self.save(update_fields=["progress_percentage", "status", "completed_date", "updated_at"])
        self.goal.update_progress()


# ---------------------------------------------------------------------------
# 5. SubGoal  (weekly level)
#    Breaks a Milestone into week-sized chunks for the Goals page.
# ---------------------------------------------------------------------------

class SubGoal(models.Model):
    """
    Weekly breakdown of monthly milestones.

    Example for "Master Python Fundamentals (January 2026)":
    - Week 1: "Learn Data Structures" (Jan 1-7)
    - Week 2: "Learn Algorithms Basics" (Jan 8-14)
    - Week 3: "Object-Oriented Programming" (Jan 15-21)
    - Week 4: "Python Projects & Practice" (Jan 22-31)
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("skipped", "Skipped"),
    ]


    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    milestone = models.ForeignKey(
        Milestone, on_delete=models.CASCADE, related_name="subgoals"
    )

    # SubGoal Details
    title = models.CharField(
        max_length=255,
        help_text="Example: 'Week 1: Learn Data Structures (Lists, Tuples, Dicts, Sets)'",
    )
    description = models.TextField(
        blank=True,
        help_text="What to focus on: 'Study Python collections, practice manipulation, solve 10 problems'",
    )
    # learning_objectives = models.JSONField(
    #     default=list,
    #     blank=True,
    #     help_text='["Master list operations", "Understand dict vs set", "Solve 10 data structure problems"]',
    # )

    # Priority & Status
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Progress
    progress_percentage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Auto-calculated from daily tasks",
    )

    # Timeline
    # week_number = models.IntegerField(
    #     null=True, blank=True, help_text="Week 1, 2, 3, 4 of the month"
    # )
    start_date = models.DateField(
        null=True, blank=True, help_text="Example: January 1, 2026 (Monday)"
    )
    target_date = models.DateField(
        null=True, blank=True, help_text="Example: January 7, 2026 (Sunday)"
    )
    completed_date = models.DateField(null=True, blank=True)
    # estimated_duration_days = models.IntegerField(
    #     default=7, help_text="Typically 7 days for weekly goals"
    # )

    # Ordering
    display_order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)

    # AI Generated
    is_ai_generated = models.BooleanField(default=True)
    ai_reasoning = models.TextField(
        blank=True,
        help_text="AI: 'Data structures are fundamental for coding interviews'",
    )

    # User Modification
    is_user_modified = models.BooleanField(default=False)
    # is_user_added = models.BooleanField(default=False)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["milestone", "display_order"]
        indexes = [
            models.Index(fields=["milestone", "status"]),
            models.Index(fields=["milestone", "start_date"]),
        ]

    def __str__(self):
        return f"{self.milestone.title} → {self.title}"
    
    @property
    def week_number(self) -> int:
        """Week number within the milestone (1-based, derived from display_order)."""
        return self.display_order + 1

    def update_progress(self):
        """Recalculate from tasks, then cascade up to the parent Milestone."""
        tasks = self.tasks.all()
        if not tasks.exists():
            return
        completed = tasks.filter(status="completed").count()
        self.progress_percentage = int((completed / tasks.count()) * 100)
        if self.progress_percentage == 100:
            self.status = "completed"
            self.completed_date = timezone.localdate()
        elif self.progress_percentage > 0:
            self.status = "in_progress"
        self.save(update_fields=["progress_percentage", "status", "completed_date", "updated_at"])
        self.milestone.update_progress()

# ---------------------------------------------------------------------------
# 6. Task  (daily level)
#    The atomic unit of work shown on the Daily Routines page.
# ---------------------------------------------------------------------------


class Task(models.Model):
    """
    Daily actionable tasks that make up weekly subgoals.

    Example for "Week 1: Learn Data Structures":
    - Day 1 (Mon): "Study Python Lists - Read docs + 2 hours practice"
    - Day 1 (Mon): "Solve 5 LeetCode Easy problems on Arrays"
    - Day 2 (Tue): "Study Tuples and immutability - 1.5 hours"
    - Day 2 (Tue): "Practice tuple operations - 3 problems"
    - Day 3 (Wed): "Study Dictionaries - Hash tables concept"
    - Day 3 (Wed): "Build a phone book app using dict"
    - Day 4 (Thu): "Study Sets and set operations"
    - Day 5 (Fri): "Review all data structures - create cheat sheet"
    - Day 6 (Sat): "Solve 10 mixed data structure problems"
    - Day 7 (Sun): "Weekly review + build mini project"
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("skipped", "Skipped"),
    ]

    

    TASK_TYPE_CHOICES = [
        ("learning", "Learning"),       # Read / watch / study
        ("practice", "Practice"),       # Coding / exercise / drill
        ("project", "Project"),         # Build something tangible
        ("review", "Review"),           # Revision / reflection
        ("assessment", "Assessment"),   # Quiz / test / self-check
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subgoal = models.ForeignKey(SubGoal, on_delete=models.CASCADE, related_name="tasks")

    # Core Details
    title = models.CharField(
        max_length=255,
        help_text="Example: 'Study Python Lists - Read documentation + 2 hours practice'",
    )
    description = models.TextField(
        blank=True,
        help_text="What exactly to do: 'Read Python docs on lists, watch 30min tutorial, practice 10 operations'",
    )
    # instructions = models.TextField(
    #     blank=True,
    #     help_text="Step-by-step: '1. Read docs 2. Watch video 3. Code along 4. Solve 5 problems'",
    # )

    # Task Type
    task_type = models.CharField(
        max_length=20, choices=TASK_TYPE_CHOICES, default="learning"
    )

    # Resources
    # resources = models.JSONField(
    #     default=list,
    #     blank=True,
    #     help_text='["https://docs.python.org/3/tutorial/datastructures.html", "LeetCode Easy Arrays"]',
    # )

    # Priority & Status
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Time Management
    scheduled_date = models.DateField(
        null=True, blank=True, help_text="Example: January 1, 2026"
    )
    scheduled_time = models.TimeField(
        null=True, blank=True, help_text="Example: 09:00 AM"
    )
    estimated_duration_minutes = models.PositiveIntegerField(
        default=60, help_text="Example: 120 minutes (2 hours)"
    )
    actual_duration_minutes = models.PositiveIntegerField(
        null=True, blank=True, help_text="How long it actually took"
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    # Ordering
    # display_order = models.IntegerField(default=0)
    # is_required = models.BooleanField(default=True)

    # Notes & Reflection
    completion_notes = models.TextField(
        blank=True,
        help_text="User's notes after completing: 'Learned list comprehensions, struggled with slicing'",
    )
    difficulty_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1=Very Easy, 5=Very Hard",
    )
    # Controls ordering within a day
    display_order = models.PositiveIntegerField(default=0)


    # AI Generated
    is_ai_generated = models.BooleanField(default=True)
    ai_reasoning = models.TextField(
        blank=True,
        help_text="AI: 'Lists are the most used data structure in Python interviews'",
    )
    is_user_modified = models.BooleanField(default=False)


    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subgoal", "scheduled_date", "display_order"]
        indexes = [
            models.Index(fields=["subgoal", "status"]),
            models.Index(fields=["subgoal", "scheduled_date"]),
            # Critical for Dashboard: fetch today's tasks across all goals
            models.Index(fields=["scheduled_date", "status"]),
        ]

    def __str__(self):
        return f"Day {self.display_order} → {self.title}"
    
    def mark_completed(
        self,
        notes: str = "",
        difficulty: int | None = None,
        actual_minutes: int | None = None,
    ):
        """
        Mark the task done and cascade progress up the hierarchy.
        Call this instead of manually setting status = 'completed'.
        """
        self.status = "completed"
        self.completed_at = timezone.now()
        self.completion_notes = notes
        self.difficulty_rating = difficulty
        self.actual_duration_minutes = actual_minutes
        self.save()
        # Cascade: Task → SubGoal → Milestone → Goal
        self.subgoal.update_progress()
