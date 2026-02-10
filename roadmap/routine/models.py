# ==============================================================================
# DAILY ROUTINE MODELS - CLEAN VERSION
# ==============================================================================
# Focus: Discipline-based daily task completion
# No duplication, production-ready
# ==============================================================================

from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid


# ==============================================================================
# 1. DAILY TASK LIST (Main container for the day)
# ==============================================================================

class DailyTaskList(models.Model):
    """
    Daily task list for a specific date
    Focus: Complete tasks TODAY (timing is flexible)
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='daily_task_lists'
    )
    
    # Which day
    date = models.DateField()
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Progress
    total_tasks = models.IntegerField(default=0)
    completed_tasks = models.IntegerField(default=0)
    completion_percentage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Discipline tracking
    is_fully_completed = models.BooleanField(
        default=False,
        help_text="All tasks completed today"
    )
    completed_on_time = models.BooleanField(
        default=False,
        help_text="All tasks completed before midnight"
    )
    
    # AI-generated motivation
    daily_motivation = models.TextField(blank=True)
    daily_mantra = models.CharField(
        max_length=255,
        blank=True,
        help_text="Short motivational phrase for the day"
    )
    
    # Timestamps
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
        return f"{self.user.email} - {self.date}"
    
    def update_progress(self):
        """Update progress based on task completion"""
        tasks = self.tasks.all()
        
        if tasks.exists():
            self.total_tasks = tasks.count()
            self.completed_tasks = tasks.filter(is_completed=True).count()
            
            if self.total_tasks > 0:
                self.completion_percentage = int(
                    (self.completed_tasks / self.total_tasks) * 100
                )
            
            # Check if fully completed
            self.is_fully_completed = (self.completed_tasks == self.total_tasks)
            
            if self.is_fully_completed and not self.completed_at:
                self.completed_at = timezone.now()
                # Check if completed before midnight
                if self.completed_at.date() == self.date:
                    self.completed_on_time = True
            
            # Update status
            if self.completed_tasks == 0:
                self.status = 'pending'
            elif self.is_fully_completed:
                self.status = 'completed'
            else:
                self.status = 'in_progress'
            
            self.save()


# ==============================================================================
# 2. DAILY TASK ITEM (Individual tasks in the list)
# ==============================================================================

class DailyTaskItem(models.Model):
    """
    Individual task for the day
    Can be EITHER:
    1. Life Habit (meditation, exercise, etc.)
    2. Goal Task (from existing Task model in goals app)
    
    KEY: Completion matters, not timing!
    """
    
    ITEM_TYPE_CHOICES = [
        ('habit', 'Daily Habit'),
        ('goal_task', 'Goal Task'),
    ]
    
    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_list = models.ForeignKey(
        DailyTaskList,
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    
    # Type
    item_type = models.CharField(max_length=15, choices=ITEM_TYPE_CHOICES)
    
    # Link to Goal Task (if applicable)
    goal_task = models.ForeignKey(
        'goal.Task',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='daily_items',
        help_text="Link to Task from goal hierarchy"
    )
    
    # Link to Habit (if applicable)
    habit = models.ForeignKey(
        'HabitTracker',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='daily_items'
    )
    
    # Task details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=10, default='✅')
    
    # Priority
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium'
    )
    
    # Time tracking
    estimated_minutes = models.IntegerField(
        default=30,
        help_text="How long this takes"
    )
    actual_minutes = models.IntegerField(
        null=True,
        blank=True,
        help_text="How long it actually took"
    )
    
    # Completion (ANYTIME during the day!)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When it was completed (anytime today is fine!)"
    )
    
    # Optional: Suggested time (guidance only)
    suggested_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Suggested time - NOT required to follow"
    )
    
    # Skipped?
    is_skipped = models.BooleanField(default=False)
    skip_reason = models.TextField(blank=True)
    
    # Notes
    completion_notes = models.TextField(blank=True)
    
    # Related goal (for context)
    related_goal = models.ForeignKey(
        'goal.Goal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='daily_items'
    )
    
    # AI-generated motivation
    why_important = models.TextField(
        blank=True,
        help_text="Why completing this today matters"
    )
    
    # Display order
    display_order = models.IntegerField(default=0)
    
    # Gamification
    points_earned = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'daily_task_items'
        ordering = ['task_list', '-priority', 'display_order']
        indexes = [
            models.Index(fields=['task_list', 'is_completed']),
            models.Index(fields=['task_list', 'priority']),
        ]
    
    def __str__(self):
        status = "✅" if self.is_completed else "⏳"
        return f"{status} {self.title}"
    
    def mark_completed(self, notes="", actual_minutes=None):
        """
        Mark as completed - ANYTIME today is acceptable!
        Discipline = doing it, not when you do it
        """
        self.is_completed = True
        self.completed_at = timezone.now()
        self.completion_notes = notes
        
        if actual_minutes:
            self.actual_minutes = actual_minutes
        
        # Award points based on priority
        if self.priority == 'high':
            self.points_earned = 20
        elif self.priority == 'medium':
            self.points_earned = 15
        else:
            self.points_earned = 10
        
        # Bonus points for completing on the same day
        if self.completed_at.date() == self.task_list.date:
            self.points_earned += 5
        
        self.save()
        
        # Update parent task list
        self.task_list.update_progress()
        
        # If this is a goal task, sync with Task model (CASCADE UPDATE!)
        if self.goal_task:
            self.goal_task.status = 'completed'
            self.goal_task.completed_at = self.completed_at
            self.goal_task.completion_notes = notes
            if actual_minutes:
                self.goal_task.actual_duration_minutes = actual_minutes
            self.goal_task.save()
            
            # Trigger progress updates up the hierarchy
            # Task → SubGoal → Milestone → Goal (all automatic!)
            self.goal_task.subgoal.update_progress()
        
        # If this is a habit, record completion
        if self.habit:
            HabitCompletion.objects.update_or_create(
                habit=self.habit,
                completion_date=self.task_list.date,
                defaults={
                    'is_completed': True,
                    'completed_at': self.completed_at,
                    'time_spent_minutes': actual_minutes,
                    'notes': notes
                }
            )
    
    def mark_skipped(self, reason=""):
        """Mark as skipped for today"""
        self.is_skipped = True
        self.skip_reason = reason
        self.save()
        
        # Update parent task list
        self.task_list.update_progress()


# ==============================================================================
# 3. HABIT TRACKER (Recurring daily habits)
# ==============================================================================

class HabitTracker(models.Model):
    """
    Define habits that should be done daily
    Examples: Meditation, Exercise, Reading, Journaling
    """
    
    FREQUENCY_CHOICES = [
        ('daily', 'Every Day'),
        ('weekdays', 'Weekdays Only'),
        ('custom', 'Custom Days'),
    ]
    
    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='habits'
    )
    
    # Habit details
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=10, default='⭐')
    
    # Why it matters
    why_important = models.TextField(
        blank=True,
        help_text="Why this habit is important for your goals"
    )
    
    # Frequency
    frequency = models.CharField(
        max_length=15,
        choices=FREQUENCY_CHOICES,
        default='daily'
    )
    custom_days = models.JSONField(
        null=True,
        blank=True,
        help_text="[0,1,2,3,4] for Mon-Fri if custom"
    )
    
    # Time estimate
    estimated_minutes = models.IntegerField(default=30)
    
    # Priority
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium'
    )
    
    # Optional: Link to goal
    linked_goal = models.ForeignKey(
        'goal.Goal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='habits'
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Streak tracking
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    total_completions = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'habit_trackers'
        ordering = ['-priority', 'name']
    
    def __str__(self):
        return f"{self.icon} {self.name}"
    
    def should_include_today(self):
        """Check if habit should be included in today's task list"""
        if not self.is_active:
            return False
        
        today = timezone.now().weekday()  # 0=Monday, 6=Sunday
        
        if self.frequency == 'daily':
            return True
        elif self.frequency == 'weekdays':
            return today < 5  # Mon-Fri
        elif self.frequency == 'custom' and self.custom_days:
            return today in self.custom_days
        
        return False


# ==============================================================================
# 4. HABIT COMPLETION (Track daily habit completion)
# ==============================================================================

class HabitCompletion(models.Model):
    """Track habit completion for each day"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    habit = models.ForeignKey(
        HabitTracker,
        on_delete=models.CASCADE,
        related_name='completions'
    )
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='habit_completions'
    )
    
    # Completion details
    completion_date = models.DateField()
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Optional details
    time_spent_minutes = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'habit_completions'
        unique_together = ['habit', 'completion_date']
        ordering = ['-completion_date']
    
    def __str__(self):
        status = "✅" if self.is_completed else "❌"
        return f"{status} {self.habit.name} - {self.completion_date}"


# ==============================================================================
# 5. DISCIPLINE STREAK (Track consecutive perfect days)
# ==============================================================================

class DisciplineStreak(models.Model):
    """
    Track user's discipline streak
    Counts consecutive days where ALL tasks were completed
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='discipline_streak'
    )
    
    # Current streak
    current_streak_days = models.IntegerField(default=0)
    current_streak_start = models.DateField(null=True, blank=True)
    
    # Longest streak
    longest_streak_days = models.IntegerField(default=0)
    longest_streak_start = models.DateField(null=True, blank=True)
    longest_streak_end = models.DateField(null=True, blank=True)
    
    # Stats
    total_perfect_days = models.IntegerField(
        default=0,
        help_text="Total days with 100% task completion"
    )
    total_days_tracked = models.IntegerField(default=0)
    
    # Last update
    last_updated = models.DateField(auto_now=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'discipline_streaks'
    
    def __str__(self):
        return f"{self.user.email} - {self.current_streak_days} day streak"
    
    def update_streak(self, date, all_tasks_completed):
        """Update streak based on whether all tasks were completed"""
        if all_tasks_completed:
            # Increment current streak
            if self.current_streak_days == 0:
                self.current_streak_start = date
            
            self.current_streak_days += 1
            self.total_perfect_days += 1
            
            # Update longest streak if needed
            if self.current_streak_days > self.longest_streak_days:
                self.longest_streak_days = self.current_streak_days
                self.longest_streak_start = self.current_streak_start
                self.longest_streak_end = date
        else:
            # Streak broken
            self.current_streak_days = 0
            self.current_streak_start = None
        
        self.total_days_tracked += 1
        self.save()