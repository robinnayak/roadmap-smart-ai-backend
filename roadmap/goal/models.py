from django.utils import timezone
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class UserCurrentSituationGoal(models.Model):
    """Structured output extracted from AI for user situation & goals"""
    
    user_personal_details = models.OneToOneField(
        "authentication.UserPersonalDetails",
        on_delete=models.CASCADE,
        related_name="current_situation_goal",
        default=None,
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
        return f"Situation & Goals | User {self.ai_processing_job.user.id}"


class Goal(models.Model):
    """
        Multi-dimensional goals that can impact multiple life areas
        Example: "Build Trading Bot SaaS" affects career, finance, and personal
    growth
    """

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

    STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("paused", "Paused"),
        ("cancelled", "Cancelled"),
    ]

    user = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.CASCADE, related_name="goals"
    )

    # Goals Details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    why_it_matters = models.TextField(
        help_text="Why this goal is important - shown to user for motivation"
    )
    primary_category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    categories = models.JSONField(
        default=list,
        blank=True,
        help_text="""
        List of categories this goal belongs to. 
        Example: ["financial", "career", "personal"]
        """
    ) 
    impact_dimensions = models.JSONField(
        default=dict,
        blank=True,
        null=True,
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

    tags = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="['side-business', 'passive-income', 'python', 'ai']",
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="not_started"
    )
    # Timeline
    start_date = models.DateField(default=timezone.localdate)
    target_date = models.DateField(null=True, blank=True)
    actual_completion_date = models.DateField(null=True, blank=True)
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
        return f"{self.title} ({self.primary_category  or  "unkown category" })"

    def save(self, *args, **kwargs):
        if not self.primary_category and self.categories:
            self.primary_category = self.categories[0]
        super().save(*args, **kwargs)
    
    @property
    def days_remaining(self):
        """Calculate remaining days until target date"""

        if self.target_date and self.status != "completed":
            delta = self.target_date - timezone.now().date()
            return delta.days
        return None

    @property
    def is_overdue(self):
        """Check if the goal is past target date"""
        if self.target_date and self.status not in ["completed", "cancelled"]:
            return timezone.now().date() > self.target_date
        return False

    def update_progress(self):
        """Calculate and update goal progress based on sub-goals"""
        pass


class GoalAttributes(models.Model):
    """
    Flexible attributes for different goal types stored as JSON
    Replaces need for separate Financial/Career/Health/Personal apps
    """

    goal = models.OneToOneField(
        Goal, on_delete=models.CASCADE, related_name="attributes"
    )
    
    #Ai processing jobs for fetching goal attribute such as financial, career, and so on (Task: Fetch user text prompt to JSON format)
    
    
    
    # ai_processing_job = models.OneToOneField('ai.AIProcessingJob', on_delete=models.CASCADE, related_name='goal_attributes', null=True, blank=True)
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
    skill_data = models.JSONField(
        null=True,
        blank=True,
        help_text="""
        {
            'skill_name': 'Machine Learning',
            'current_level': 'Intermediate',
            'target_level': 'Advanced',
            'courses': ['Coursera ML', 'Fast.ai'],
            'courses_completed': 1,
            'practice_hours_target': 200,
            'practice_hours_current': 120,
            'projects_completed': 3,
            'certification_target': 'TensorFlow Developer'
        }
        """,
    )

    # Custom attributes for any other type
    custom_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Any other custom attributes specific to this goal",
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Attributes for {self.goal.title}"
