# ==============================================================================
# roadmap/routine/models.py
# ==============================================================================

import uuid
from datetime import timedelta
from django.apps import apps
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


# ==============================================================================
# 1. HealthProfile
# ==============================================================================

class HealthProfile(models.Model):
    JOB_TYPE_CHOICES = [
        ('desk', 'Desk/Office'),
        ('physical', 'Physical/Field'),
        ('creative', 'Creative'),
        ('healthcare', 'Healthcare'),
        ('student', 'Student'),
        ('freelance', 'Freelance'),
        ('other', 'Other'),
    ]
    SLEEP_PATTERN_CHOICES = [
        ('early_riser', 'Early Riser'),
        ('night_owl', 'Night Owl'),
        ('irregular', 'Irregular'),
        ('shift_based', 'Shift-based'),
    ]
    BUDGET_CHOICES = [
        ('minimal', 'Minimal (free only)'),
        ('low', 'Low ($1-20/mo)'),
        ('medium', 'Medium'),
        ('flexible', 'Flexible'),
    ]
    MOTIVATION_STYLE_CHOICES = [
        ('reward', 'Reward-driven'),
        ('progress', 'Progress tracking'),
        ('accountability', 'Accountability partner'),
        ('intrinsic', 'Intrinsic'),
    ]
    WILLPOWER_CHOICES = [
        ('low', 'Low - need tiny habits'),
        ('medium', 'Medium'),
        ('high', 'High - push me'),
    ]
    STRESS_LEVEL_CHOICES = [
        ('low', 'Low'),
        ('moderate', 'Moderate'),
        ('high', 'High'),
        ('burnout', 'Burnout'),
    ]
    FITNESS_LEVEL_CHOICES = [
        ('sedentary', 'Sedentary'),
        ('light', 'Light activity'),
        ('moderate', 'Moderate'),
        ('active', 'Active'),
        ('athletic', 'Athletic'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='health_profiles',
    )

    bad_habits = models.JSONField(default=list)
    conditions = models.JSONField(default=list)
    on_medication = models.BooleanField(default=False)
    condition_duration = models.CharField(max_length=20, blank=True)

    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES, blank=True)
    job_type_other = models.CharField(max_length=100, blank=True)
    work_hours = models.CharField(max_length=50, blank=True)
    sleep_pattern = models.CharField(max_length=20, choices=SLEEP_PATTERN_CHOICES, blank=True)
    climate = models.CharField(max_length=50, blank=True)
    budget_level = models.CharField(max_length=10, choices=BUDGET_CHOICES, default='minimal')

    age_range = models.CharField(max_length=10, blank=True)
    gender = models.CharField(max_length=30, blank=True)
    weight_goal = models.CharField(max_length=30, blank=True)

    motivation_style = models.CharField(max_length=20, choices=MOTIVATION_STYLE_CHOICES, blank=True)
    willpower_level = models.CharField(max_length=10, choices=WILLPOWER_CHOICES, default='medium')
    stress_level = models.CharField(max_length=10, choices=STRESS_LEVEL_CHOICES, default='moderate')
    past_failures = models.JSONField(default=list)

    fitness_level = models.CharField(max_length=15, choices=FITNESS_LEVEL_CHOICES, default='sedentary')
    diet_type = models.CharField(max_length=50, blank=True)
    food_restrictions = models.TextField(blank=True)
    existing_habits = models.JSONField(default=list)

    primary_goal = models.CharField(max_length=100, blank=True)
    goal_timeframe = models.CharField(max_length=20, blank=True)
    daily_time_available = models.CharField(max_length=20, blank=True)

    commitment_words = models.TextField(blank=True)
    commitment_person = models.CharField(max_length=100, blank=True)
    commitment_emoji = models.CharField(max_length=10, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'health_profiles'

    def __str__(self):
        return f"{self.user.email} - health profile"

    def as_ai_context(self) -> dict:
        return {
            'bad_habits': self.bad_habits,
            'conditions': self.conditions,
            'on_medication': self.on_medication,
            'job_type': self.job_type,
            'job_type_other': self.job_type_other,
            'sleep_pattern': self.sleep_pattern,
            'budget_level': self.budget_level,
            'age_range': self.age_range,
            'fitness_level': self.fitness_level,
            'willpower_level': self.willpower_level,
            'stress_level': self.stress_level,
            'motivation_style': self.motivation_style,
            'primary_goal': self.primary_goal,
            'goal_timeframe': self.goal_timeframe,
            'daily_time': self.daily_time_available,
            'existing_habits': self.existing_habits,
            'diet_type': self.diet_type,
            'food_restrictions': self.food_restrictions,
            'commitment_words': self.commitment_words,
            'commitment_person': self.commitment_person,
        }


# ==============================================================================
# 2. DailyTaskList
# ==============================================================================

class DailyTaskList(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='daily_task_lists',
    )
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    total_tasks = models.IntegerField(default=0)
    completed_tasks = models.IntegerField(default=0)
    completion_percentage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    is_fully_completed = models.BooleanField(default=False)
    completed_on_time = models.BooleanField(
        default=False,
        help_text="All tasks completed before midnight on the scheduled date",
    )

    daily_motivation = models.TextField(blank=True)
    daily_mantra = models.CharField(max_length=255, blank=True)
    schedule_constraints = models.JSONField(
        default=dict,
        blank=True,
        help_text="Event-aware scheduling metadata for routine-fit explanation.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'daily_task_lists'
        unique_together = ['user', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'is_fully_completed']),
        ]

    def __str__(self):
        return f"{self.user.email} — {self.date}"

    def update_progress(self):
        """
        Recalculate progress from child tasks and save only the changed fields.

        FIX: Uses update_fields=[...] instead of a full save() to avoid
             overwriting concurrent writes and to reduce DB write load.
        """
        tasks = self.tasks.all()

        if not tasks.exists():
            return

        total     = tasks.count()
        completed = tasks.filter(is_completed=True).count()
        pct       = int((completed / total) * 100) if total else 0
        fully     = completed == total

        # Determine status
        if completed == 0:
            new_status = 'pending'
        elif fully:
            new_status = 'completed'
        else:
            new_status = 'in_progress'

        # Only set completed_at once — don't overwrite if already set
        now = timezone.now()
        completed_at = self.completed_at
        on_time = self.completed_on_time

        if fully and not self.completed_at:
            completed_at = now
            on_time = completed_at.date() == self.date

        self.total_tasks          = total
        self.completed_tasks      = completed
        self.completion_percentage = pct
        self.is_fully_completed   = fully
        self.status               = new_status
        self.completed_at         = completed_at
        self.completed_on_time    = on_time

        self.save(update_fields=[
            'total_tasks', 'completed_tasks', 'completion_percentage',
            'is_fully_completed', 'status', 'completed_at', 'completed_on_time',
            'updated_at',
        ])


# ==============================================================================
# 3. DailyTaskItem
# ==============================================================================

class DailyTaskItem(models.Model):

    ITEM_TYPE_CHOICES = [
        ('habit',     'Daily Habit'),
        ('goal_task', 'Goal Task'),
        ('event',     'Event'),
        ('journal',   'Journal'),
    ]
    PRIORITY_CHOICES = [
        ('high',   'High'),
        ('medium', 'Medium'),
        ('low',    'Low'),
    ]
    TIME_SLOT_CHOICES = [
        ('morning', 'Morning'),
        ('afternoon', 'Afternoon'),
        ('evening', 'Evening'),
    ]
    # Numeric weight used for ordering (higher = more urgent)
    PRIORITY_ORDER = {'high': 3, 'medium': 2, 'low': 1}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_list = models.ForeignKey(
        DailyTaskList, on_delete=models.CASCADE, related_name='tasks'
    )
    item_type = models.CharField(max_length=15, choices=ITEM_TYPE_CHOICES)

    goal_task = models.ForeignKey(
        'goal.Task',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='daily_items',
    )
    habit = models.ForeignKey(
        'HabitTracker',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='daily_items',
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='daily_items',
    )

    title       = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    icon        = models.CharField(max_length=10, default='✅')
    priority    = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')

    estimated_minutes = models.IntegerField(default=30)
    actual_minutes    = models.IntegerField(null=True, blank=True)

    is_completed     = models.BooleanField(default=False)
    completed_at     = models.DateTimeField(null=True, blank=True)
    time_slot        = models.CharField(max_length=10, choices=TIME_SLOT_CHOICES, null=True, blank=True)
    suggested_time   = models.TimeField(null=True, blank=True)

    is_skipped       = models.BooleanField(default=False)
    skip_reason      = models.TextField(blank=True)
    completion_notes = models.TextField(blank=True)

    related_goal = models.ForeignKey(
        'goal.Goal',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='daily_items',
    )
    why_important = models.TextField(blank=True)
    display_order = models.IntegerField(default=0)
    points_earned = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_task_items'
        # FIX: Cannot order by CharField 'priority' correctly (alphabetical gives wrong order).
        #      Use display_order only here; views/serializers use annotated ordering.
        ordering = ['task_list', 'display_order']
        indexes = [
            models.Index(fields=['task_list', 'is_completed']),
            models.Index(fields=['task_list', 'priority']),
            models.Index(fields=['task_list', 'time_slot']),
        ]

    def __str__(self):
        marker = '✅' if self.is_completed else '⏳'
        return f"{self.task_list.user.email}{marker} {self.title}"

    def mark_completed(self, notes: str = "", actual_minutes: int | None = None):
        """
        Mark this item as completed and cascade updates to the goal hierarchy
        and habit tracker.

        FIX: For goal_task items, calls goal_task.mark_completed() instead of
             manually setting fields. This ensures the cascade
             Task → SubGoal → Milestone → Goal runs through the single
             authoritative path defined on the Task model.
        """
        self.is_completed     = True
        self.completed_at     = timezone.now()
        self.completion_notes = notes
        if actual_minutes:
            self.actual_minutes = actual_minutes

        # Points based on priority
        base_points = {'high': 20, 'medium': 15, 'low': 10}
        self.points_earned = base_points.get(self.priority, 10)
        # Bonus for completing on the scheduled day
        if self.completed_at.date() == self.task_list.date:
            self.points_earned += 5

        self.save()

        # Cascade 1: update the parent DailyTaskList
        self.task_list.update_progress()

        # Cascade 2: sync with the Goal hierarchy via Task.mark_completed()
        # FIX: Use the Task model's own method — it handles status, completed_at,
        #      actual_duration_minutes, and the full upward cascade in one place.
        if self.goal_task:
            self.goal_task.mark_completed(
                notes=notes,
                actual_minutes=actual_minutes,
            )

        # Cascade 3: record habit completion and update HabitTracker streaks
        if self.habit:
            HabitCompletion.objects.update_or_create(
                habit=self.habit,
                completion_date=self.task_list.date,
                defaults={
                    'user':                self.habit.user,
                    'is_completed':        True,
                    'completed_at':        self.completed_at,
                    'time_spent_minutes':  actual_minutes,
                    'notes':               notes,
                },
            )
            # FIX: Update HabitTracker streak counters — previously never called,
            #      so current_streak / longest_streak always read 0.
            self.habit.record_completion(date=self.task_list.date)

    def mark_skipped(self, reason: str = ""):
        self.is_skipped  = True
        self.skip_reason = reason
        self.save(update_fields=['is_skipped', 'skip_reason', 'updated_at'])
        self.task_list.update_progress()
        
    @property
    def primary_category(self) -> str:
        if self.related_goal:
            return self.related_goal.primary_category
        if self.event_id:
            return 'Event'
        return ''


# ==============================================================================
# 4. HabitTracker
# ==============================================================================

class HabitTracker(models.Model):

    FREQUENCY_CHOICES = [
        ('daily',    'Every Day'),
        ('weekdays', 'Weekdays Only'),
        ('custom',   'Custom Days'),
    ]
    PRIORITY_CHOICES = [
        ('high',   'High'),
        ('medium', 'Medium'),
        ('low',    'Low'),
    ]
    CATEGORY_CHOICES = [
        ('hydration', 'Hydration'),
        ('movement', 'Movement'),
        ('nutrition', 'Nutrition'),
        ('breathing', 'Breathing'),
        ('mental', 'Mental/Mindfulness'),
        ('sleep', 'Sleep'),
        ('other', 'Other'),
    ]

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='habits',
    )

    name         = models.CharField(max_length=255)
    description  = models.TextField(blank=True)
    icon         = models.CharField(max_length=10, default='⭐')
    category     = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='other')
    why_important = models.TextField(blank=True)
    reason_headline = models.CharField(max_length=200, blank=True)
    reason_body = models.TextField(blank=True)
    science_badge = models.CharField(max_length=100, blank=True)
    rewards = models.JSONField(default=list)
    proof_metric_name = models.CharField(max_length=100, blank=True)

    frequency    = models.CharField(max_length=15, choices=FREQUENCY_CHOICES, default='daily')
    custom_days  = models.JSONField(
        null=True, blank=True,
        help_text="List of weekday ints [0–6] where 0=Monday. Used when frequency='custom'.",
    )
    estimated_minutes = models.IntegerField(default=30)
    suggested_time = models.TimeField(null=True, blank=True)
    priority    = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')

    linked_goal = models.ForeignKey(
        'goal.Goal',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='habits',
    )
    ai_suggested = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # Streak counters — updated by record_completion()
    current_streak    = models.IntegerField(default=0)
    longest_streak    = models.IntegerField(default=0)
    total_completions = models.IntegerField(default=0)
    last_completed_date = models.DateField(
        null=True, blank=True,
        help_text="Last date the habit was completed. Used to detect streak breaks.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'habit_trackers'
        ordering = ['-priority', 'name']

    def __str__(self):
        return f"{self.user.email} - {self.icon} {self.name}"

    def should_include_today(self) -> bool:
        return self.should_include_on_date(timezone.localdate())

    def should_include_on_date(self, target_date) -> bool:
        if not self.is_active:
            return False
        weekday = target_date.weekday()  # 0=Monday, 6=Sunday
        if self.frequency == 'daily':
            return True
        elif self.frequency == 'weekdays':
            return weekday < 5
        elif self.frequency == 'custom' and self.custom_days:
            return weekday in self.custom_days
        return False

    def record_completion(self, date):
        """
        Update streak counters after a completion is recorded for `date`.

        FIX: This method was missing — HabitCompletion records were created
             by DailyTaskItem.mark_completed() but current_streak / longest_streak
             / total_completions on HabitTracker were never updated, so they
             always read 0.

        Also guards against double-counting the same date (idempotent).
        """
        if self.last_completed_date == date:
            # Already counted this date — do nothing
            return

        yesterday = date - timezone.timedelta(days=1)

        if self.last_completed_date == yesterday:
            # Continuing an existing streak
            self.current_streak += 1
        else:
            # Streak broken or first completion
            self.current_streak = 1

        self.total_completions += 1
        self.last_completed_date = date

        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak

        self.save(update_fields=[
            'current_streak', 'longest_streak',
            'total_completions', 'last_completed_date', 'updated_at',
        ])

    def get_current_proof(self) -> dict | None:
        if not self.linked_goal_id or not self.proof_metric_name:
            return None

        try:
            goal_progress_entry_model = apps.get_model('routine', 'GoalProgressEntry')
        except LookupError:
            return None

        entries = goal_progress_entry_model.objects.filter(
            goal_id=self.linked_goal_id,
            metric_name=self.proof_metric_name,
        ).order_by('date')

        if not entries.exists():
            return None

        first_entry = entries.first()
        latest_entry = entries.last()
        return {
            'metric_name': self.proof_metric_name,
            'start_value': first_entry.metric_value,
            'current_value': latest_entry.metric_value,
            'target_value': latest_entry.metric_target,
            'unit': latest_entry.metric_unit,
            'direction': latest_entry.metric_direction,
            'progress_pct': latest_entry.progress_percentage,
            'days_tracked': entries.count(),
        }


# ==============================================================================
# 5. HabitRecommendation
# ==============================================================================

class HabitRecommendation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('snoozed', 'Snoozed'),
    ]
    CATEGORY_CHOICES = [
        ('hydration', 'Hydration'),
        ('movement', 'Movement'),
        ('nutrition', 'Nutrition'),
        ('breathing', 'Breathing'),
        ('mental', 'Mental/Mindfulness'),
        ('sleep', 'Sleep'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='habit_recommendations',
    )
    suggested_for_goal = models.ForeignKey(
        'goal.Goal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='habit_recommendations',
    )
    source_health_profile = models.ForeignKey(
        'HealthProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='habit_recommendations',
    )

    name = models.CharField(max_length=255)
    icon = models.CharField(max_length=10, default='⭐')
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='other')
    estimated_minutes = models.IntegerField(default=30)
    suggested_time = models.TimeField(null=True, blank=True)
    frequency = models.CharField(max_length=15, default='daily')

    reason_headline = models.CharField(max_length=200, blank=True)
    reason_body = models.TextField(blank=True)
    science_badge = models.CharField(max_length=100, blank=True)
    rewards = models.JSONField(default=list)
    proof_metric_name = models.CharField(max_length=100, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    snooze_until = models.DateField(null=True, blank=True)
    habit_tracker = models.OneToOneField(
        'HabitTracker',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='from_recommendation',
    )

    ai_model_used = models.CharField(max_length=50, blank=True)
    generation_batch = models.UUIDField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'habit_recommendations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', 'suggested_for_goal']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.icon} {self.name} [{self.status}]"

    def accept(self) -> HabitTracker:
        if self.status == 'accepted' and self.habit_tracker:
            return self.habit_tracker

        habit_description = (self.reason_body or "").strip()
        habit_why_important = (self.reason_headline or "").strip()

        if not habit_description and habit_why_important:
            habit_description = habit_why_important

        tracker = HabitTracker.objects.create(
            user=self.user,
            name=self.name,
            description=habit_description,
            icon=self.icon,
            category=self.category,
            why_important=habit_why_important,
            estimated_minutes=self.estimated_minutes,
            suggested_time=self.suggested_time,
            frequency=self.frequency,
            reason_headline=self.reason_headline,
            reason_body=self.reason_body,
            science_badge=self.science_badge,
            rewards=self.rewards,
            proof_metric_name=self.proof_metric_name,
            linked_goal=self.suggested_for_goal,
            ai_suggested=True,
        )
        self.status = 'accepted'
        self.habit_tracker = tracker
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'habit_tracker', 'reviewed_at', 'updated_at'])
        return tracker

    def reject(self):
        self.status = 'rejected'
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_at', 'updated_at'])

    def snooze(self, until_date):
        self.status = 'snoozed'
        self.snooze_until = until_date
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'snooze_until', 'reviewed_at', 'updated_at'])


# ==============================================================================
# 6. GoalProgressEntry
# ==============================================================================

class GoalProgressEntry(models.Model):
    METRIC_DIRECTION_CHOICES = [
        ('up', 'Higher is better'),
        ('down', 'Lower is better'),
    ]
    DOMAIN_CHOICES = [
        ('physical', 'Physical'),
        ('mental', 'Mental'),
        ('lifestyle', 'Lifestyle'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    goal = models.ForeignKey(
        'goal.Goal',
        on_delete=models.CASCADE,
        related_name='progress_entries',
    )
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='goal_progress_entries',
    )

    date = models.DateField()
    metric_name = models.CharField(max_length=100)
    metric_value = models.FloatField()
    metric_unit = models.CharField(max_length=20)
    metric_direction = models.CharField(
        max_length=5,
        choices=METRIC_DIRECTION_CHOICES,
        default='up',
    )
    domain = models.CharField(
        max_length=15,
        choices=DOMAIN_CHOICES,
        default='physical',
    )
    metric_start = models.FloatField(help_text="Day 1 value - denormalized for fast reads")
    metric_target = models.FloatField()
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'goal_progress_entries'
        unique_together = ['goal', 'date', 'metric_name']
        ordering = ['goal', 'date']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['goal', 'date']),
            models.Index(fields=['goal', 'metric_name']),
        ]

    def __str__(self):
        return f"{self.goal} - {self.metric_name}: {self.metric_value}{self.metric_unit} ({self.date})"

    @property
    def progress_percentage(self) -> int:
        span = abs(self.metric_target - self.metric_start)
        if span == 0:
            return 100
        pct = (
            (self.metric_value - self.metric_start) / span
            if self.metric_direction == 'up'
            else (self.metric_start - self.metric_value) / span
        )
        return max(0, min(100, int(pct * 100)))


# ==============================================================================
# 7. DailyBrief
# ==============================================================================

class DailyBrief(models.Model):
    TRACK_STATUS_CHOICES = [
        ('on_track', 'On Track'),
        ('behind', 'Slightly Behind'),
        ('struggling', 'Struggling'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='daily_briefs',
    )
    date = models.DateField()
    brief_text = models.TextField()

    habit_completion_yesterday = models.FloatField(default=0.0)
    missed_habits_yesterday = models.JSONField(default=list)
    goal_metrics_snapshot = models.JSONField(default=dict)
    upcoming_events_today = models.JSONField(default=list)
    streak_at_generation = models.IntegerField(default=0)

    track_status = models.CharField(max_length=15, choices=TRACK_STATUS_CHOICES, blank=True)
    track_status_set_at = models.DateTimeField(null=True, blank=True)

    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_briefs'
        unique_together = ['user', 'date']
        ordering = ['-date']

    def __str__(self):
        return f"{self.user.email} - brief {self.date}"

    def set_track_status(self, status: str):
        self.track_status = status
        self.track_status_set_at = timezone.now()
        self.save(update_fields=['track_status', 'track_status_set_at', 'updated_at'])


# ==============================================================================
# 8. HabitCompletion
# ==============================================================================

class HabitCompletion(models.Model):

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    habit = models.ForeignKey(HabitTracker, on_delete=models.CASCADE, related_name='completions')
    user  = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='habit_completions',
    )

    completion_date  = models.DateField()
    is_completed     = models.BooleanField(default=False)
    completed_at     = models.DateTimeField(null=True, blank=True)
    time_spent_minutes = models.IntegerField(null=True, blank=True)
    notes            = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'habit_completions'
        unique_together = ['habit', 'completion_date']
        ordering = ['-completion_date']

    def __str__(self):
        marker = '✅' if self.is_completed else '❌'
        return f"{marker} {self.habit.name} — {self.completion_date}"


# ==============================================================================
# 9. DisciplineStreak
# ==============================================================================

class DisciplineStreak(models.Model):
    """
    Tracks consecutive days where the user completed ALL tasks.
    One record per user (OneToOneField).
    """

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='discipline_streak',
    )

    current_streak_days  = models.IntegerField(default=0)
    current_streak_start = models.DateField(null=True, blank=True)
    longest_streak_days  = models.IntegerField(default=0)
    longest_streak_start = models.DateField(null=True, blank=True)
    longest_streak_end   = models.DateField(null=True, blank=True)

    total_perfect_days  = models.IntegerField(default=0)
    total_days_tracked  = models.IntegerField(default=0)

    # FIX: Track which date was last processed to prevent double-counting
    last_tracked_date = models.DateField(
        null=True, blank=True,
        help_text="The most recent date that was passed to update_streak().",
    )

    last_updated = models.DateField(auto_now=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'discipline_streaks'

    def __str__(self):
        return f"{self.user.email} — {self.current_streak_days} day streak"

    def update_streak(self, date, all_tasks_completed: bool):
        """
        Update streak for a given date.

        FIX 1: Guard against double-counting — if update_streak is called
               twice for the same date (two tasks complete within the same day),
               only the first call takes effect.
        FIX 2: Guard against future dates — passing tomorrow's date would
               corrupt the streak counter.
        FIX 3: Uses update_fields=[...] instead of a full save().
        """
        today = timezone.localdate()

        # Reject future dates
        if date > today:
            return

        # Idempotent — don't process the same date twice
        if self.last_tracked_date == date:
            return

        if all_tasks_completed:
            if self.current_streak_days == 0:
                self.current_streak_start = date
            self.current_streak_days += 1
            self.total_perfect_days  += 1

            if self.current_streak_days > self.longest_streak_days:
                self.longest_streak_days  = self.current_streak_days
                self.longest_streak_start = self.current_streak_start
                self.longest_streak_end   = date
        else:
            # Streak broken
            self.current_streak_days  = 0
            self.current_streak_start = None

        self.total_days_tracked += 1
        self.last_tracked_date   = date

        self.save(update_fields=[
            'current_streak_days', 'current_streak_start',
            'longest_streak_days', 'longest_streak_start', 'longest_streak_end',
            'total_perfect_days', 'total_days_tracked', 'last_tracked_date',
            'updated_at',
        ])

    def calculate_custom_interval_streak(self, interval_days: int = 1, as_of_date=None) -> dict:
        """
        Calculate streak continuity over custom intervals (N-day windows).

        Rule:
        - A window is counted as successful if at least one perfect day
          (DailyTaskList.is_fully_completed=True) exists in that interval.
        - `current_streak_intervals` counts consecutive successful windows
          from `as_of_date` backward.
        """
        interval_days = max(1, min(int(interval_days or 1), 30))
        as_of_date = as_of_date or timezone.localdate()

        perfect_dates = list(
            DailyTaskList.objects.filter(
                user=self.user,
                is_fully_completed=True,
                date__lte=as_of_date,
            )
            .values_list("date", flat=True)
            .distinct()
            .order_by("date")
        )
        if not perfect_dates:
            return {
                "interval_days": interval_days,
                "current_streak_intervals": 0,
                "longest_streak_intervals": 0,
                "successful_intervals": 0,
            }

        perfect_date_set = set(perfect_dates)
        earliest_date = perfect_dates[0]
        interval_hits: list[bool] = []

        window_index = 0
        while True:
            window_end = as_of_date - timedelta(days=(interval_days * window_index))
            if window_end < earliest_date:
                break
            window_start = window_end - timedelta(days=interval_days - 1)
            has_hit = any(
                (window_start + timedelta(days=offset)) in perfect_date_set
                for offset in range(interval_days)
            )
            interval_hits.append(has_hit)
            window_index += 1

        current = 0
        for hit in interval_hits:
            if not hit:
                break
            current += 1

        longest = 0
        running = 0
        for hit in interval_hits:
            if hit:
                running += 1
                if running > longest:
                    longest = running
            else:
                running = 0

        return {
            "interval_days": interval_days,
            "current_streak_intervals": current,
            "longest_streak_intervals": longest,
            "successful_intervals": sum(1 for hit in interval_hits if hit),
        }


# ==============================================================================
# 10. RoutineDayModeCheckIn
# ==============================================================================

class RoutineDayModeCheckIn(models.Model):
    DAY_MODE_CHOICES = [
        ("focused", "Focused"),
        ("flex", "Flex/Unplanned"),
    ]
    SOURCE_CHOICES = [
        ("explicit", "Explicit request payload"),
        ("carry_forward", "Carried from previous day"),
        ("default", "Default focused mode"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "authentication.CustomUser",
        on_delete=models.CASCADE,
        related_name="routine_day_mode_checkins",
    )
    date = models.DateField()
    day_mode = models.CharField(max_length=10, choices=DAY_MODE_CHOICES, default="focused")
    day_mode_note = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="default")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "routine_day_mode_checkins"
        unique_together = ["user", "date"]
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "day_mode"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.date} [{self.day_mode}]"


# ==============================================================================
# 11. AdaptiveRoadmapState
# ==============================================================================

class AdaptiveRoadmapState(models.Model):
    """
    Persisted adaptive roadmap state used by routine generation triggers.

    This model stores rolling miss/success counters and scaling control values
    so adaptive behavior remains deterministic across process restarts.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "authentication.CustomUser",
        on_delete=models.CASCADE,
        related_name="adaptive_roadmap_state",
    )

    current_scale_level = models.IntegerField(default=0)
    consecutive_miss_days = models.IntegerField(default=0)
    consecutive_success_days = models.IntegerField(default=0)
    weekly_miss_days = models.IntegerField(default=0)

    last_evaluated_date = models.DateField(null=True, blank=True)
    last_scale_change_date = models.DateField(null=True, blank=True)
    weekly_reset_anchor = models.DateField(null=True, blank=True)
    last_sunday_rebuild_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "adaptive_roadmap_states"

    def __str__(self):
        return (
            f"{self.user.email} - scale={self.current_scale_level}, "
            f"miss={self.consecutive_miss_days}, success={self.consecutive_success_days}"
        )


# ==============================================================================
# 12. WakeInteraction
# ==============================================================================

class WakeInteraction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "authentication.CustomUser",
        on_delete=models.CASCADE,
        related_name="wake_interactions",
    )
    local_date = models.DateField()
    first_interaction_at = models.DateTimeField()
    timezone_name = models.CharField(max_length=64, default="UTC")
    source_path = models.CharField(max_length=255, blank=True)
    source_method = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wake_interactions"
        unique_together = ["user", "local_date"]
        ordering = ["-local_date", "-first_interaction_at"]
        indexes = [
            models.Index(fields=["user", "local_date"]),
            models.Index(fields=["user", "first_interaction_at"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.local_date} @ {self.first_interaction_at.isoformat()}"


# ==============================================================================
# 13. WakeBaselineState
# ==============================================================================

class WakeBaselineState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "authentication.CustomUser",
        on_delete=models.CASCADE,
        related_name="wake_baseline_state",
    )

    baseline_minutes = models.IntegerField(null=True, blank=True)
    baseline_time = models.TimeField(null=True, blank=True)
    baseline_timezone = models.CharField(max_length=64, default="UTC")
    last_computed_at = models.DateTimeField(null=True, blank=True)
    last_update_reason = models.CharField(max_length=100, blank=True)
    last_sample_count = models.IntegerField(default=0)
    last_valid_sample_count = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wake_baseline_states"
        indexes = [
            models.Index(fields=["baseline_timezone", "updated_at"]),
        ]

    def __str__(self):
        return (
            f"{self.user.email} - baseline={self.baseline_minutes}min "
            f"({self.baseline_timezone})"
        )
