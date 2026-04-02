import uuid

from django.db import models
from django.db.models import Q


class GIESession(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_READY_TO_FINALIZE = 'ready_to_finalize'
    STATUS_FINALIZED = 'finalized'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_READY_TO_FINALIZE, 'Ready To Finalize'),
        (STATUS_FINALIZED, 'Finalized'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PHASE_INTAKE = 'intake'
    PHASE_QUESTION_LOOP = 'question_loop'
    PHASE_REVIEW = 'review'
    PHASE_FINALIZED = 'finalized'
    PHASE_CHOICES = [
        (PHASE_INTAKE, 'Intake'),
        (PHASE_QUESTION_LOOP, 'Question Loop'),
        (PHASE_REVIEW, 'Review'),
        (PHASE_FINALIZED, 'Finalized'),
    ]

    DOMAIN_CAREER = 'career'
    DOMAIN_HEALTH = 'health'
    DOMAIN_FINANCIAL = 'financial'
    DOMAIN_LEARNING = 'learning'
    DOMAIN_PERSONAL = 'personal'
    DOMAIN_BUSINESS = 'business'
    DOMAIN_OTHER = 'other'
    GOAL_DOMAIN_CHOICES = [
        (DOMAIN_CAREER, 'Career'),
        (DOMAIN_HEALTH, 'Health'),
        (DOMAIN_FINANCIAL, 'Financial'),
        (DOMAIN_LEARNING, 'Learning'),
        (DOMAIN_PERSONAL, 'Personal'),
        (DOMAIN_BUSINESS, 'Business'),
        (DOMAIN_OTHER, 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.CASCADE,
        related_name='gie_sessions',
    )
    goal_text = models.TextField()
    goal_domain = models.CharField(max_length=20, choices=GOAL_DOMAIN_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    phase = models.CharField(max_length=20, choices=PHASE_CHOICES, default=PHASE_INTAKE)
    current_question = models.TextField(null=True, blank=True)
    total_questions = models.PositiveIntegerField(default=5)
    current_question_number = models.PositiveIntegerField(default=1)
    required_slot_count = models.IntegerField(default=0)
    filled_required_slot_count = models.IntegerField(default=0)
    completeness_percent = models.FloatField(default=0.0)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gie_sessions'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', 'phase']),
            models.Index(fields=['user', '-updated_at']),
        ]

    def __str__(self):
        return f'{self.user.email} - {self.goal_domain} [{self.status}]'


class GIETurn(models.Model):
    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_SYSTEM = 'system'
    ROLE_CHOICES = [
        (ROLE_USER, 'User'),
        (ROLE_ASSISTANT, 'Assistant'),
        (ROLE_SYSTEM, 'System'),
    ]

    KIND_GOAL_STATEMENT = 'goal_statement'
    KIND_SLOT_ANSWER = 'slot_answer'
    KIND_FOLLOWUP_QUESTION = 'followup_question'
    KIND_CLARIFICATION = 'clarification'
    KIND_CONFIRMATION = 'confirmation'
    KIND_CHOICES = [
        (KIND_GOAL_STATEMENT, 'Goal Statement'),
        (KIND_SLOT_ANSWER, 'Slot Answer'),
        (KIND_FOLLOWUP_QUESTION, 'Followup Question'),
        (KIND_CLARIFICATION, 'Clarification'),
        (KIND_CONFIRMATION, 'Confirmation'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        GIESession,
        on_delete=models.CASCADE,
        related_name='turns',
    )
    turn_index = models.PositiveIntegerField()
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    content = models.TextField()
    client_turn_id = models.CharField(max_length=100, null=True, blank=True)
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gie_turns'
        ordering = ['turn_index', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'turn_index'],
                name='unique_gie_turn_index_per_session',
            ),
            models.UniqueConstraint(
                fields=['session', 'client_turn_id'],
                condition=Q(client_turn_id__isnull=False),
                name='unique_gie_client_turn_id_per_session',
            ),
        ]
        indexes = [
            models.Index(fields=['session', 'turn_index']),
            models.Index(fields=['session', 'created_at']),
        ]

    def __str__(self):
        return f'{self.session_id} - turn {self.turn_index} ({self.role})'


class GIESlotDefinition(models.Model):
    TYPE_STRING = 'string'
    TYPE_NUMBER = 'number'
    TYPE_INTEGER = 'integer'
    TYPE_BOOLEAN = 'boolean'
    TYPE_DATE = 'date'
    TYPE_ENUM = 'enum'
    TYPE_LIST_STRING = 'list_string'
    DATA_TYPE_CHOICES = [
        (TYPE_STRING, 'String'),
        (TYPE_NUMBER, 'Number'),
        (TYPE_INTEGER, 'Integer'),
        (TYPE_BOOLEAN, 'Boolean'),
        (TYPE_DATE, 'Date'),
        (TYPE_ENUM, 'Enum'),
        (TYPE_LIST_STRING, 'List String'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        GIESession,
        on_delete=models.CASCADE,
        related_name='slot_definitions',
    )
    key = models.CharField(max_length=120)
    label = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    required = models.BooleanField(default=False)
    data_type = models.CharField(max_length=20, choices=DATA_TYPE_CHOICES)
    enum_values = models.JSONField(null=True, blank=True)
    validation = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gie_slot_definitions'
        ordering = ['required', 'key']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'key'],
                name='unique_gie_slot_definition_key_per_session',
            ),
        ]
        indexes = [
            models.Index(fields=['session', 'required']),
            models.Index(fields=['session', 'data_type']),
        ]

    def __str__(self):
        marker = 'required' if self.required else 'optional'
        return f'{self.session_id}:{self.key} ({marker})'


class GIESlotState(models.Model):
    SOURCE_GOAL_TEXT = 'goal_text'
    SOURCE_TURN_ANSWER = 'turn_answer'
    SOURCE_INFERENCE = 'inference'
    SOURCE_SYSTEM_DEFAULT = 'system_default'
    SOURCE_CHOICES = [
        (SOURCE_GOAL_TEXT, 'Goal Text'),
        (SOURCE_TURN_ANSWER, 'Turn Answer'),
        (SOURCE_INFERENCE, 'Inference'),
        (SOURCE_SYSTEM_DEFAULT, 'System Default'),
    ]

    STATUS_MISSING = 'missing'
    STATUS_PARTIAL = 'partial'
    STATUS_FILLED = 'filled'
    STATUS_LOCKED = 'locked'
    STATUS_CHOICES = [
        (STATUS_MISSING, 'Missing'),
        (STATUS_PARTIAL, 'Partial'),
        (STATUS_FILLED, 'Filled'),
        (STATUS_LOCKED, 'Locked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        GIESession,
        on_delete=models.CASCADE,
        related_name='slot_states',
    )
    slot_key = models.CharField(max_length=120)
    required = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_MISSING)
    value = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    last_updated_turn_index = models.PositiveIntegerField(null=True, blank=True)
    missing_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gie_slot_states'
        ordering = ['slot_key']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'slot_key'],
                name='unique_gie_slot_state_key_per_session',
            ),
        ]
        indexes = [
            models.Index(fields=['session', 'status']),
            models.Index(fields=['session', 'required']),
        ]

    def __str__(self):
        return f'{self.session_id}:{self.slot_key} [{self.status}]'


class GIEPlanSnapshot(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_FINALIZED = 'finalized'
    STATUS_SUPERSEDED = 'superseded'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_FINALIZED, 'Finalized'),
        (STATUS_SUPERSEDED, 'Superseded'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        GIESession,
        on_delete=models.CASCADE,
        related_name='plan_snapshots',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    goal_summary = models.TextField()
    assumptions = models.JSONField(default=list, blank=True)
    risks = models.JSONField(default=list, blank=True)
    milestones = models.JSONField(default=list, blank=True)
    weekly_routine_guidance = models.JSONField(default=list, blank=True)
    rie_signal = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gie_plan_snapshots'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.session_id} - {self.status}'


class GIEAdaptationProposal(models.Model):
    TRIGGER_MISSED_TASKS_STREAK = 'missed_tasks_streak'
    TRIGGER_DECLINING_ENGAGEMENT = 'declining_engagement'
    TRIGGER_NEGATIVE_SENTIMENT = 'negative_sentiment'
    TRIGGER_STALLED_PROGRESS = 'stalled_progress'
    TRIGGER_TIMELINE_CHANGE = 'timeline_change'
    TRIGGER_CHOICES = [
        (TRIGGER_MISSED_TASKS_STREAK, 'Missed Tasks Streak'),
        (TRIGGER_DECLINING_ENGAGEMENT, 'Declining Engagement'),
        (TRIGGER_NEGATIVE_SENTIMENT, 'Negative Sentiment'),
        (TRIGGER_STALLED_PROGRESS, 'Stalled Progress'),
        (TRIGGER_TIMELINE_CHANGE, 'Timeline Change'),
    ]

    ACTION_REDUCE_SCOPE = 'reduce_scope'
    ACTION_RESEQUENCE_MILESTONES = 'resequence_milestones'
    ACTION_INCREASE_SUPPORT = 'increase_support'
    ACTION_ADJUST_TIMELINE = 'adjust_timeline'
    ACTION_SWAP_COMMITMENT = 'swap_commitment'
    ACTION_CHOICES = [
        (ACTION_REDUCE_SCOPE, 'Reduce Scope'),
        (ACTION_RESEQUENCE_MILESTONES, 'Resequence Milestones'),
        (ACTION_INCREASE_SUPPORT, 'Increase Support'),
        (ACTION_ADJUST_TIMELINE, 'Adjust Timeline'),
        (ACTION_SWAP_COMMITMENT, 'Swap Commitment'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        GIESession,
        on_delete=models.CASCADE,
        related_name='adaptation_proposals',
    )
    trigger = models.CharField(max_length=40, choices=TRIGGER_CHOICES)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    reason = models.TextField()
    changes = models.JSONField(default=list, blank=True)
    recommended_commitment_updates = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gie_adaptation_proposals'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', '-created_at']),
            models.Index(fields=['session', 'trigger']),
        ]

    def __str__(self):
        return f'{self.session_id} - {self.trigger} -> {self.action}'


class GIESessionAnalytics(models.Model):
    STAGE_INTAKE = "intake"
    STAGE_QUESTION_LOOP = "question_loop"
    STAGE_REVIEW = "review"
    STAGE_FINALIZED = "finalized"
    STAGE_ADAPTATION = "adaptation"
    STAGE_FALLBACK = "fallback"
    STAGE_BLOCKED = "blocked"
    STAGE_CHOICES = [
        (STAGE_INTAKE, "Intake"),
        (STAGE_QUESTION_LOOP, "Question Loop"),
        (STAGE_REVIEW, "Review"),
        (STAGE_FINALIZED, "Finalized"),
        (STAGE_ADAPTATION, "Adaptation"),
        (STAGE_FALLBACK, "Fallback"),
        (STAGE_BLOCKED, "Blocked"),
    ]

    session = models.OneToOneField(
        GIESession,
        on_delete=models.CASCADE,
        related_name="analytics",
    )
    turn_count = models.PositiveIntegerField(default=0)
    turns_to_ready_to_finalize = models.PositiveIntegerField(null=True, blank=True)
    time_to_ready_seconds = models.PositiveIntegerField(null=True, blank=True)
    time_to_finalize_seconds = models.PositiveIntegerField(null=True, blank=True)
    schema_completeness_progress = models.JSONField(default=list, blank=True)
    plan_review_entered = models.BooleanField(default=False)
    plan_accepted = models.BooleanField(default=False)
    finalize_attempt_count = models.PositiveIntegerField(default=0)
    finalize_success_count = models.PositiveIntegerField(default=0)
    adaptation_request_count = models.PositiveIntegerField(default=0)
    fallback_activation_count = models.PositiveIntegerField(default=0)
    degradation_event_count = models.PositiveIntegerField(default=0)
    last_fallback_reason_code = models.CharField(max_length=120, null=True, blank=True)
    last_stage = models.CharField(
        max_length=32,
        choices=STAGE_CHOICES,
        default=STAGE_INTAKE,
    )
    drop_off_stage = models.CharField(max_length=32, choices=STAGE_CHOICES, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gie_session_analytics"
        indexes = [
            models.Index(fields=["plan_accepted"]),
            models.Index(fields=["last_stage"]),
            models.Index(fields=["drop_off_stage"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.session_id} analytics"
