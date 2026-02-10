"""
AI Processing Models - Production Ready
========================================
Handles AI job processing for roadmap generation and goal analysis.
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid


class AIProcessingJob(models.Model):
    """
    Tracks AI processing jobs for roadmap generation, goal analysis, etc.
    
    Usage:
    1. User submits goal/situation text
    2. AIProcessingJob created with status='PENDING'
    3. Background worker processes job
    4. Result stored in related models (UserCurrentSituationGoal, GoalAttributes, etc.)
    """
    
    # Job Status
    JOB_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Job Types
    JOB_TYPE_CHOICES = [
        ('situation_analysis', 'Analyze Current Situation'),
        ('goal_generation', 'Generate Goals & Roadmap'),
        ('goal_attributes', 'Extract Goal Attributes'),
        ('milestone_generation', 'Generate Milestones'),
        ('task_generation', 'Generate Daily Tasks'),
        ('habit_suggestion', 'Suggest Habits'),
        ('progress_analysis', 'Analyze Progress'),
        ('motivation_generation', 'Generate Motivation'),
    ]
    
    # Primary Key
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False
    )
    
    # Relationships
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='ai_jobs',
        db_index=True
    )
    
    # Job Details
    job_type = models.CharField(
        max_length=50,
        choices=JOB_TYPE_CHOICES,
        db_index=True
    )
    
    # Input Data
    user_raw_text = models.TextField(
        blank=True,
        help_text="Raw user input text for AI processing"
    )
    
    input_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        Structured input for AI processing:
        {
            'current_age': 25,
            'target_age': 30,
            'situation': '...',
            'goals': [...],
            'constraints': [...]
        }
        """
    )
    
    # Output Data
    output_data = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="AI-generated structured output"
    )
    
    raw_ai_response = models.TextField(
        blank=True,
        help_text="Complete raw response from AI model"
    )
    
    # Status & Progress
    status = models.CharField(
        max_length=20,
        choices=JOB_STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    progress_percentage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Job completion progress (0-100%)"
    )
    
    # Error Handling
    error_message = models.TextField(
        blank=True,
        help_text="Error details if job failed"
    )
    
    retry_count = models.IntegerField(
        default=0,
        help_text="Number of retry attempts"
    )
    
    max_retries = models.IntegerField(
        default=3,
        help_text="Maximum retry attempts allowed"
    )
    
    # AI Model Info
    ai_model_used = models.CharField(
        max_length=100,
        blank=True,
        help_text="AI model identifier (e.g., 'claude-sonnet-4', 'ollama-llama3')"
    )
    
    ai_tokens_used = models.IntegerField(
        default=0,
        help_text="Total tokens consumed by this job"
    )
    
    ai_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0.0000,
        help_text="Estimated cost in USD"
    )
    
    # Performance Metrics
    processing_time_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Total processing time in seconds"
    )
    
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When processing actually started"
    )
    
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When processing completed"
    )
    
    # Priority
    priority = models.IntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Job priority (1=lowest, 10=highest)"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Additional Context
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional context/metadata for the job"
    )
    
    class Meta:
        db_table = 'ai_processing_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', 'job_type']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
        verbose_name = 'AI Processing Job'
        verbose_name_plural = 'AI Processing Jobs'
    
    def __str__(self):
        return f"{self.get_job_type_display()} - {self.get_status_display()} ({self.id})"
    
    def start_processing(self):
        """Mark job as started"""
        self.status = 'processing'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at', 'updated_at'])
    
    def mark_completed(self, output_data, raw_response="", model_used="", tokens=0, cost=0.0):
        """Mark job as successfully completed"""
        processing_time = None
        if self.started_at:
            processing_time = (timezone.now() - self.started_at).total_seconds()
        
        self.status = 'completed'
        self.output_data = output_data
        self.raw_ai_response = raw_response
        self.ai_model_used = model_used
        self.ai_tokens_used = tokens
        self.ai_cost_usd = cost
        self.progress_percentage = 100
        self.completed_at = timezone.now()
        self.processing_time_seconds = processing_time
        
        self.save(update_fields=[
            'status', 'output_data', 'raw_ai_response', 'ai_model_used',
            'ai_tokens_used', 'ai_cost_usd', 'progress_percentage',
            'completed_at', 'processing_time_seconds', 'updated_at'
        ])
    
    def mark_failed(self, error_message):
        """Mark job as failed"""
        self.status = 'failed'
        self.error_message = error_message
        self.retry_count += 1
        
        if self.started_at:
            self.processing_time_seconds = (timezone.now() - self.started_at).total_seconds()
        
        self.save(update_fields=[
            'status', 'error_message', 'retry_count', 
            'processing_time_seconds', 'updated_at'
        ])
    
    def can_retry(self):
        """Check if job can be retried"""
        return self.retry_count < self.max_retries and self.status == 'failed'
    
    def retry(self):
        """Retry failed job"""
        if self.can_retry():
            self.status = 'pending'
            self.error_message = ''
            self.progress_percentage = 0
            self.started_at = None
            self.completed_at = None
            self.save(update_fields=[
                'status', 'error_message', 'progress_percentage',
                'started_at', 'completed_at', 'updated_at'
            ])
            return True
        return False
    
    def update_progress(self, percentage, message=""):
        """Update job progress"""
        self.progress_percentage = min(max(0, percentage), 100)
        if message:
            self.metadata['progress_message'] = message
        self.save(update_fields=['progress_percentage', 'metadata', 'updated_at'])
    
    @property
    def is_complete(self):
        """Check if job is complete"""
        return self.status == 'completed'
    
    @property
    def is_processing(self):
        """Check if job is currently processing"""
        return self.status == 'processing'
    
    @property
    def has_failed(self):
        """Check if job has failed"""
        return self.status == 'failed'


class AIModelUsageStats(models.Model):
    """
    Track AI model usage statistics for cost monitoring and optimization.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='ai_usage_stats'
    )
    
    # Time Period
    date = models.DateField(
        default=timezone.now,
        db_index=True,
        help_text="Statistics for this date"
    )
    
    # Usage Metrics
    total_jobs = models.IntegerField(default=0)
    successful_jobs = models.IntegerField(default=0)
    failed_jobs = models.IntegerField(default=0)
    
    total_tokens = models.IntegerField(default=0)
    total_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0.0000
    )
    
    # Model Breakdown
    model_usage = models.JSONField(
        default=dict,
        help_text="""
        {
            'claude-sonnet-4': {'jobs': 10, 'tokens': 50000, 'cost': 1.25},
            'ollama-llama3': {'jobs': 5, 'tokens': 20000, 'cost': 0.0}
        }
        """
    )
    
    # Job Type Breakdown
    job_type_usage = models.JSONField(
        default=dict,
        help_text="""
        {
            'situation_analysis': {'count': 1, 'tokens': 5000},
            'goal_generation': {'count': 3, 'tokens': 15000}
        }
        """
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ai_model_usage_stats'
        unique_together = ['user', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['user', '-date']),
        ]
        verbose_name = 'AI Usage Statistics'
        verbose_name_plural = 'AI Usage Statistics'
    
    def __str__(self):
        return f"{self.user.email} - {self.date} - {self.total_jobs} jobs"


class AIPromptTemplate(models.Model):
    """
    Store and version AI prompt templates for different job types.
    Allows A/B testing and optimization of prompts.
    """
    
    TEMPLATE_TYPE_CHOICES = [
        ('situation_analysis', 'Situation Analysis'),
        ('goal_generation', 'Goal Generation'),
        ('milestone_generation', 'Milestone Generation'),
        ('task_generation', 'Task Generation'),
        ('motivation', 'Motivation Generation'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Template Details
    name = models.CharField(max_length=255)
    template_type = models.CharField(
        max_length=50,
        choices=TEMPLATE_TYPE_CHOICES,
        db_index=True
    )
    
    version = models.CharField(
        max_length=20,
        default='1.0',
        help_text="Template version for tracking changes"
    )
    
    # Prompt Content
    system_prompt = models.TextField(
        help_text="System prompt that sets AI behavior and context"
    )
    
    user_prompt_template = models.TextField(
        help_text="User prompt template with placeholders like {user_input}, {age}, etc."
    )
    
    # Configuration
    temperature = models.FloatField(
        default=0.7,
        validators=[MinValueValidator(0.0), MaxValueValidator(2.0)],
        help_text="AI temperature setting (0.0 = deterministic, 2.0 = creative)"
    )
    
    max_tokens = models.IntegerField(
        default=4000,
        help_text="Maximum tokens for AI response"
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this template is currently in use"
    )
    
    is_default = models.BooleanField(
        default=False,
        help_text="Default template for this type"
    )
    
    # Performance Metrics
    usage_count = models.IntegerField(
        default=0,
        help_text="Number of times this template has been used"
    )
    
    success_rate = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Success rate percentage"
    )
    
    average_quality_score = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(5.0)],
        help_text="Average user satisfaction score (1-5)"
    )
    
    # Metadata
    created_by = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_prompt_templates'
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Notes about this template version"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ai_prompt_templates'
        ordering = ['-is_default', '-is_active', 'template_type', '-version']
        indexes = [
            models.Index(fields=['template_type', 'is_active']),
            models.Index(fields=['template_type', 'is_default']),
        ]
        verbose_name = 'AI Prompt Template'
        verbose_name_plural = 'AI Prompt Templates'
    
    def __str__(self):
        status = "✓" if self.is_active else "✗"
        default = " [DEFAULT]" if self.is_default else ""
        return f"{status} {self.name} v{self.version}{default}"
    
    def increment_usage(self):
        """Increment usage counter"""
        self.usage_count += 1
        self.save(update_fields=['usage_count', 'updated_at'])
    
    def update_success_rate(self, was_successful):
        """Update success rate based on job outcome"""
        total = self.usage_count
        if total == 0:
            return
        
        current_successes = (self.success_rate / 100) * (total - 1)
        if was_successful:
            current_successes += 1
        
        self.success_rate = (current_successes / total) * 100
        self.save(update_fields=['success_rate', 'updated_at'])