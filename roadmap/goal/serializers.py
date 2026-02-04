from rest_framework import serializers
from .models import UserCurrentSituationGoal, GoalAttributes, Goal, Milestone, SubGoal, Task
from django.utils import timezone
from datetime import datetime
from ai.services.text_extraction import GoalAttributeExtractor
from authentication.serializers import UserPersonalDetailsSerializer



class UserCurrentSituationGoalSerializer(serializers.ModelSerializer):
    user_personal_details = UserPersonalDetailsSerializer(read_only=True, allow_null=True)
    

    class Meta:
        model = UserCurrentSituationGoal
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "ai_processing_job",
            "user_personal_details",
        ]

    def validate_current_situation(self, value):
        """Validate current_situation is a dict/JSON object"""
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("current_situation must be a JSON object")
        return value

    def validate_key_skills(self, value):
        """Validate key_skills is a list"""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("key_skills must be a list")
        return value

    def validate_main_goals(self, value):
        """Validate main_goals is a list"""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("main_goals must be a list")
        return value

    def validate_constraints(self, value):
        """Validate constraints is a list"""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("constraints must be a list")
        return value

    def validate_priority_areas(self, value):
        """Validate priority_areas is a list"""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("priority_areas must be a list")
        return value

    def validate_current_role(self, value):
        """Validate current_role length"""
        if value and len(value) > 255:
            raise serializers.ValidationError(
                "current_role cannot exceed 255 characters"
            )
        return value

    def validate_time_availability(self, value):
        """Validate time_availability length"""
        if value and len(value) > 255:
            raise serializers.ValidationError(
                "time_availability cannot exceed 255 characters"
            )
        return value

    def validate_age(self, value):
        """Validate age is reasonable"""
        if value is not None:
            if value < 0 or value > 120:
                raise serializers.ValidationError("Age must be between 0 and 120")
        return value





class GoalListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views"""

    days_remaining = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Goal
        fields = [
            "id",
            "title",
            "primary_category",
            "categories",
            "priority",
            "status",
            "progress_percentage",
            "target_date",
            "days_remaining",
            "is_overdue",
            "is_ai_generated",
            "tags",
        ]

    def get_days_remaining(self, obj):
        return obj.days_remaining

    def get_is_overdue(self, obj):
        return obj.is_overdue







          

class TaskSerializer(serializers.ModelSerializer):
    """Serializer for Task model"""
    
    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'instructions',
            'task_type', 'resources', 'priority', 'status',
            'scheduled_date', 'scheduled_time',
            'estimated_duration_minutes', 'actual_duration_minutes',
            'completed_at', 'display_order', 'is_required',
            'completion_notes', 'difficulty_rating',
            'is_ai_generated', 'ai_reasoning', 'is_user_modified',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        

class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight Task serializer for lists"""
    
    class Meta:
        model = Task
        fields = [
            'id', 'title', 'status', 'priority',
            'scheduled_date', 'estimated_duration_minutes',
            'display_order'
        ]
        


class SubGoalSerializer(serializers.ModelSerializer):
    """Serializer for SubGoal with nested tasks"""
    
    tasks = TaskSerializer(many=True, read_only=True)
    task_count = serializers.SerializerMethodField()
    completed_task_count = serializers.SerializerMethodField()
    
    class Meta:
        model = SubGoal
        fields = [
            'id', 'title', 'description', 'learning_objectives',
            'priority', 'status', 'progress_percentage',
            'week_number', 'start_date', 'target_date', 'completed_date',
            'estimated_duration_days', 'display_order', 'is_required',
            'is_ai_generated', 'ai_reasoning', 'is_user_modified',
            'tasks', 'task_count', 'completed_task_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'progress_percentage']
    
    def get_task_count(self, obj):
        return obj.tasks.count()
    
    def get_completed_task_count(self, obj):
        return obj.tasks.filter(status='completed').count()
  

class SubGoalListSerializer(serializers.ModelSerializer):
    """Lightweight SubGoal serializer without tasks"""
    
    task_count = serializers.SerializerMethodField()
    completed_task_count = serializers.SerializerMethodField()
    
    class Meta:
        model = SubGoal
        fields = [
            'id', 'title', 'status', 'progress_percentage',
            'week_number', 'display_order',
            'task_count', 'completed_task_count'
        ]
    
    def get_task_count(self, obj):
        return obj.tasks.count()
    
    def get_completed_task_count(self, obj):
        return obj.tasks.filter(status='completed').count()


class MilestoneSerializer(serializers.ModelSerializer):
    """Serializer for Milestone with nested subgoals and tasks"""
    
    subgoals = SubGoalSerializer(many=True, read_only=True)
    subgoal_count = serializers.SerializerMethodField()
    completed_subgoal_count = serializers.SerializerMethodField()
    total_task_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Milestone
        fields = [
            'id', 'title', 'description', 'success_criteria',
            'priority', 'status', 'progress_percentage',
            'month_year', 'start_date', 'target_date', 'completed_date',
            'estimated_duration_days', 'display_order', 'is_required',
            'is_ai_generated', 'ai_reasoning', 'is_user_modified',
            'subgoals', 'subgoal_count', 'completed_subgoal_count',
            'total_task_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'progress_percentage']
    
    def get_subgoal_count(self, obj):
        return obj.subgoals.count()
    
    def get_completed_subgoal_count(self, obj):
        return obj.subgoals.filter(status='completed').count()
    
    def get_total_task_count(self, obj):
        return Task.objects.filter(subgoal__milestone=obj).count()


class MilestoneListSerializer(serializers.ModelSerializer):
    """Lightweight Milestone serializer without nested data"""
    
    subgoal_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Milestone
        fields = [
            'id', 'title', 'status', 'progress_percentage',
            'month_year', 'display_order', 'subgoal_count'
        ]
    
    def get_subgoal_count(self, obj):
        return obj.subgoals.count()
     


# ==============================================================================
# GOAL ATTRIBUTES SERIALIZER
# ==============================================================================

class GoalAttributesSerializer(serializers.ModelSerializer):
    """Serializer for GoalAttributes"""
    
    class Meta:
        model = GoalAttributes
        fields = [
            'id', 'financial_data', 'career_data', 'health_data',
            'personal_data', 'skill_data', 'custom_data',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class GoalSerializer(serializers.ModelSerializer):
    """
    Serializer for Goal model with extracted attributes support.
    """
    
    # Computed fields
    days_remaining = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    
    # Include GoalAttributes in the response (read-only)
    attributes = GoalAttributesSerializer(read_only=True)
    # Write-only field for extracting attributes from natural language
    goal_attributes_input = serializers.CharField(
        write_only=True, 
        required=False, 
        allow_blank=True,
        help_text="Natural language description to extract goal attributes from"
    )

    class Meta:
        model = Goal
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "is_user_modified",
            "ai_generation_context",
            "actual_completion_date",
            "user",
            "attributes"
        ]
        extra_fields = ['goal_attributes_input'] 

    def get_days_remaining(self, obj) -> int:
        """Calculate days remaining until target date."""
        return obj.days_remaining

    def get_is_overdue(self, obj) -> bool:
        """Check if goal is past its target date."""
        return obj.is_overdue

    def validate_impact_dimensions(self, value):
        """Validate impact_dimensions is a JSON object."""
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError(
                "impact_dimensions must be a JSON object"
            )
        return value

    def validate_tags(self, value):
        """Validate tags is a list of strings."""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("tags must be a list")
        
        # Ensure all tags are strings
        if value and any(not isinstance(tag, str) for tag in value):
            raise serializers.ValidationError("All tags must be strings")
            
        return value

    def validate_target_date(self, value):
        """Validate target_date is not in the past."""
        if value < timezone.now().date():
            raise serializers.ValidationError("Target date cannot be in the past")
        return value

    def validate_progress_percentage(self, value):
        """Validate progress percentage is between 0 and 100."""
        if not 0 <= value <= 100:
            raise serializers.ValidationError(
                "Progress percentage must be between 0 and 100"
            )
        return value

    def validate_ai_feasibility_score(self, value):
        """Validate AI feasibility score is between 0.0 and 1.0."""
        if value is not None and not 0.0 <= value <= 1.0:
            raise serializers.ValidationError(
                "AI feasibility score must be between 0.0 and 1.0"
            )
        return value

    

    def _extract_and_create_attributes(self, goal, user_input, user, goal_id):
        """Extract attributes from user input and create/update GoalAttributes."""
        try:
            extractor = GoalAttributeExtractor()
            result = extractor.extract_goal_attributes(user_input=user_input, user=user, goal_id = str(goal_id))
            
            if result.get("status") == "success" and "data" in result:
                extracted_data = result["data"]
                
                # Determine which category-specific field to use
                category = extracted_data.get("goal_category", "").lower()
                category_fields = {
                    "financial": "financial_data",
                    "career": "career_data",
                    "health": "health_data",
                    "personal": "personal_data"
                }
                
                # Check if GoalAttributes already exists for this goal
                try:
                    goal_attributes = GoalAttributes.objects.get(goal=goal)
                    
                    # Update existing GoalAttributes
                    goal_attributes.custom_data = extracted_data
                    
                    # Clear all category-specific fields first
                    goal_attributes.financial_data = None
                    goal_attributes.career_data = None
                    goal_attributes.health_data = None
                    goal_attributes.personal_data = None
                    goal_attributes.skill_data = None
                    
                    # Set the appropriate category field
                    if category in category_fields:
                        setattr(goal_attributes, category_fields[category], extracted_data)
                    
                    # Update AI processing job reference if available
                    if "job_id" in result:
                        goal_attributes.ai_processing_job_id = result["job_id"]
                    
                    goal_attributes.save()
                    print(f"✓ Updated existing GoalAttributes ID: {goal_attributes.id} for goal {goal.id}")
                    
                    return True
                    
                except GoalAttributes.DoesNotExist:
                    # Create new GoalAttributes
                    goal_attrs_data = {
                        "goal": goal,
                        "custom_data": extracted_data,
                    }
                    
                    # Set the appropriate category field
                    if category in category_fields:
                        goal_attrs_data[category_fields[category]] = extracted_data
                    
                    # Add AI processing job reference if available
                    if "job_id" in result:
                        goal_attrs_data["ai_processing_job_id"] = result["job_id"]
                    
                    # Create GoalAttributes
                    goal_attributes = GoalAttributes.objects.create(**goal_attrs_data)
                    print(f"✓ Created new GoalAttributes ID: {goal_attributes.id} for goal {goal.id}")
                    
                    return True
                    
        except Exception as e:
            print(f"✗ Error extracting or creating goal attributes: {str(e)}")
            import traceback
            traceback.print_exc()
            
        return False
    
    def create(self, validated_data):
        """
        Create a new goal with optional extracted attributes.
        """
        # Extract user input for attribute extraction
        goal_attributes_input = validated_data.pop("goal_attributes_input", None)
        
        # Mark as user-modified if not AI-generated
        if not validated_data.get("is_ai_generated", False):
            validated_data["is_user_modified"] = True
        try:
            # Create the goal
            goal = Goal.objects.create(**validated_data)
            goal_id = goal.id
            
            print(f"Created goal ID: {goal.id} | Title: {goal.title}")
            
            # Extract and create attributes if user input provided
            if goal_attributes_input:
                user = self.context.get('request').user
                success = self._extract_and_create_attributes(goal, goal_attributes_input, user, goal_id)
                if success:
                    print(f"✓ Extracted and created attributes for goal ID: {goal.id}")
                else:
                    print(f"✗ Failed to extract and create attributes for goal ID: {goal.id}")
            
            return goal
        except Exception as e:
            print(f"✗ Error creating goal: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
            
        


    def update(self, instance, validated_data):
        """
        Update an existing goal.
        
        Note: Attribute extraction only happens during creation.
        Updates to existing goals should modify GoalAttributes directly.
        """
        # Remove the extraction field if present (only used during creation)
        validated_data.pop("goal_attributes_input", None)
        
        # Mark as user-modified if editing AI-generated goal
        if instance.is_ai_generated and not validated_data.get("is_ai_generated", True):
            validated_data["is_user_modified"] = True
        
        # Update main goal fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save()
        
        return instance
    
# ==============================================================================
# GOAL SERIALIZERS
# ==============================================================================

class GoalDetailSerializer(serializers.ModelSerializer):
    """Complete Goal serializer with full hierarchy"""
    
    attributes = GoalAttributesSerializer(read_only=True)
    milestones = MilestoneSerializer(many=True, read_only=True)
    
    # Computed fields
    days_remaining = serializers.ReadOnlyField()
    is_overdue = serializers.ReadOnlyField()
    
    # Statistics
    milestone_count = serializers.SerializerMethodField()
    completed_milestone_count = serializers.SerializerMethodField()
    total_subgoal_count = serializers.SerializerMethodField()
    total_task_count = serializers.SerializerMethodField()
    completed_task_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Goal
        fields = [
            'id', 'title', 'description', 'why_it_matters', 'key_skills',
            'primary_category', 'categories', 'impact_dimensions', 'tags',
            'priority', 'status', 'progress_percentage',
            'start_date', 'target_date', 'actual_completion_date',
            'days_remaining', 'is_overdue',
            'is_ai_generated', 'ai_feasibility_score', 'ai_generation_context',
            'is_user_modified',
            'attributes', 'milestones',
            'milestone_count', 'completed_milestone_count',
            'total_subgoal_count', 'total_task_count', 'completed_task_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'days_remaining', 'is_overdue']
    
    def get_milestone_count(self, obj):
        return obj.milestones.count()
    
    def get_completed_milestone_count(self, obj):
        return obj.milestones.filter(status='completed').count()
    
    def get_total_subgoal_count(self, obj):
        return SubGoal.objects.filter(milestone__goal=obj).count()
    
    def get_total_task_count(self, obj):
        return Task.objects.filter(subgoal__milestone__goal=obj).count()
    
    def get_completed_task_count(self, obj):
        return Task.objects.filter(
            subgoal__milestone__goal=obj,
            status='completed'
        ).count()


class GoalListSerializer(serializers.ModelSerializer):
    """Lightweight Goal serializer for lists"""
    
    days_remaining = serializers.ReadOnlyField()
    is_overdue = serializers.ReadOnlyField()
    milestone_count = serializers.SerializerMethodField()
    completed_milestones = serializers.SerializerMethodField()
    total_tasks = serializers.SerializerMethodField()
    completed_tasks = serializers.SerializerMethodField()
    
    class Meta:
        model = Goal
        fields = [
            'id', 'title', 'description', 'status', 'progress_percentage',
            'priority', 'primary_category', 'categories',
            'target_date', 'days_remaining', 'is_overdue',
            'milestone_count', 'completed_milestones',
            'total_tasks', 'completed_tasks'
        ]
    
    def get_milestone_count(self, obj):
        return obj.milestones.count()
    
    def get_completed_milestones(self, obj):
        return obj.milestones.filter(status='completed').count()
    
    def get_total_tasks(self, obj):
        return Task.objects.filter(subgoal__milestone__goal=obj).count()
    
    def get_completed_tasks(self, obj):
        return Task.objects.filter(
            subgoal__milestone__goal=obj,
            status='completed'
        ).count()


class GoalCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating goals"""
    
    class Meta:
        model = Goal
        fields = [
            'title', 'description', 'why_it_matters', 'key_skills',
            'primary_category', 'categories', 'tags', 'priority',
            'start_date', 'target_date'
        ]
    
    def create(self, validated_data):
        # User will be added in the view
        return super().create(validated_data)