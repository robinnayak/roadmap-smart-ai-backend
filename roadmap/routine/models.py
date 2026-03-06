# ==============================================================================
# roadmap/routine/models.py
# ==============================================================================

import uuid
from datetime import timedelta
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


# ==============================================================================
# 1. DailyTaskList
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
# 2. DailyTaskItem
# ==============================================================================

class DailyTaskItem(models.Model):

    ITEM_TYPE_CHOICES = [
        ('habit',     'Daily Habit'),
        ('goal_task', 'Goal Task'),
        ('event',     'Event'),
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
# 3. HabitTracker
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

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='habits',
    )

    name         = models.CharField(max_length=255)
    description  = models.TextField(blank=True)
    icon         = models.CharField(max_length=10, default='⭐')
    why_important = models.TextField(blank=True)

    frequency    = models.CharField(max_length=15, choices=FREQUENCY_CHOICES, default='daily')
    custom_days  = models.JSONField(
        null=True, blank=True,
        help_text="List of weekday ints [0–6] where 0=Monday. Used when frequency='custom'.",
    )
    estimated_minutes = models.IntegerField(default=30)
    priority    = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')

    linked_goal = models.ForeignKey(
        'goal.Goal',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='habits',
    )
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


# ==============================================================================
# 4. HabitCompletion
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
# 5. DisciplineStreak
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
# 6. AdaptiveRoadmapState
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
