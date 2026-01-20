from rest_framework import serializers
from .models import UserCurrentSituationGoal, GoalAttributes, Goal
from django.utils import timezone
from datetime import datetime




class UserCurrentSituationGoalSerializer(serializers.ModelSerializer):
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


class GoalAttributesSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoalAttributes
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "goal"]

    def validate_financial_data(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("financial_data must be a JSON object")
        return value

    def validate_health_data(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("health_data must be a JSON object")
        return value

    def validate_personal_data(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("personal_data must be a JSON object")
        return value

    def validate_skill_data(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("skill_data must be a JSON object")
        return value

    def validate_career_data(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("career_data must be a JSON object")
        return value

    def validate_custom_data(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("custom_data must be a JSON object")
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



class GoalSerializer(serializers.ModelSerializer):
    attributes = GoalAttributesSerializer(required=False)
    days_remaining = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    target_date = serializers.DateField()
    
    
    # No need to explicitly define date fields unless you want custom format
    # DRF will automatically handle the conversion

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
        ]
        
    

    def get_days_remaining(self, obj):
        """Calculate days remaining for the goal"""
        return obj.days_remaining

    def get_is_overdue(self, obj):
        """Check if goal is overdue"""
        return obj.is_overdue

    def validate_impact_dimensions(self, value):
        """Validate impact_dimensions is a JSON object"""
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("impact_dimensions must be a JSON object")
        return value

    def validate_tags(self, value):
        """Validate tags is a list"""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("tags must be a list")
        return value

    def validate_target_date(self, value):
        """Validate target_date is not in the past"""
        # 'value' is already a date object here (DRF handles conversion)
        if value < timezone.now().date():
            raise serializers.ValidationError("Target date cannot be in the past")
        return value

    def validate_progress_percentage(self, value):
        """Validate progress percentage is between 0 and 100"""
        if not 0 <= value <= 100:
            raise serializers.ValidationError(
                "Progress percentage must be between 0 and 100"
            )
        return value

    def validate_ai_feasibility_score(self, value):
        """Validate feasibility score is between 0.0 and 1.0"""
        if value is not None and not 0.0 <= value <= 1.0:
            raise serializers.ValidationError(
                "Feasibility score must be between 0.0 and 1.0"
            )
        return value
    

    def create(self, validated_data):
        """
        Create a new goal
        - Automatically sets user (handled in view)
        - Marks as user_modified if not AI-generated
        - Handles nested attributes if provided
        """
        # DEBUG: Print what we're creating
        print(f"Creating goal with data: {validated_data}")
        
        # DON'T call .date() on target_date - it's already a date object
        # Remove this line: print("Validating goal target date:", validated_data["target_date"].date())
        
        # Handle nested attributes creation
        attributes_data = validated_data.pop("attributes", None)

        # If goal is being created by user (not AI), set is_user_modified to True
        if not validated_data.get("is_ai_generated", False):
            validated_data["is_user_modified"] = True

        # Create the goal
        goal = Goal.objects.create(**validated_data)
        
        print("=======================================")
        print(f"Created goal with ID: {goal.id}")
        print("=======================================")

        # Create attributes if provided
        if attributes_data:
            GoalAttributes.objects.create(goal=goal, **attributes_data)

        return goal

    def update(self, instance, validated_data):
        """
        Update an existing goal
        - Handles nested attributes update
        - Marks as user_modified if editing AI-generated goal
        """
        # Handle nested attributes update
        attributes_data = validated_data.pop("attributes", None)

        # If goal was AI generated and user is modifying it, mark as user modified
        if instance.is_ai_generated and not validated_data.get("is_ai_generated", True):
            validated_data["is_user_modified"] = True

        # Update main goal fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        # Update attributes if provided
        if attributes_data is not None:
            if hasattr(instance, "attributes"):
                attr_serializer = GoalAttributesSerializer(
                    instance.attributes, data=attributes_data, partial=True
                )
                if attr_serializer.is_valid():
                    attr_serializer.save()
            else:
                GoalAttributes.objects.create(goal=instance, **attributes_data)

        return instance

