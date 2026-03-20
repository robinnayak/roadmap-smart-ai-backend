# authentication/serializers.py

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser, Profile, NotificationSettings, UserPersonalDetails
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import IntegerField, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone


User = get_user_model()


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
        validators=[validate_password],
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ("email", "username", "password", "password2")
        extra_kwargs = {
            "username": {"required": False, "allow_blank": True},
            "email": {"required": True},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists.", code="email_taken"
            )
        return value

    def validate(self, attrs):
        if attrs.get("password") != attrs.get("password2"):
            raise serializers.ValidationError(
                {"password": "The two password fields didn't match."},
                code="password_mismatch",
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Remove non-model fields
        password = validated_data.pop("password")
        validated_data.pop("password2", None)  # safe, in case it's still there

        email = validated_data.pop("email")  # required field → must exist
        username = validated_data.pop("username", None)

        # Auto-generate username if not provided
        if not username:
            # Make base more username-friendly
            base = email.split("@")[0].lower()
            base = "".join(c for c in base if c.isalnum() or c in "_-")  # safer
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base}{counter}"
                counter += 1

        # Create the user using the proper manager method
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,  # create_user calls set_password internally
            **validated_data,  # forward any extra validated fields
        )

        # Optional: create related models here or via signals
        # Profile.objects.create(user=user)

        return user


class UserProfileSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True, help_text="Whether the account is active")
    date_joined = serializers.DateTimeField(
        read_only=True,
        format="%Y-%m-%d %H:%M:%S",
        help_text="Account creation date"
    )
    last_login = serializers.DateTimeField(
        read_only=True,
        format="%Y-%m-%d %H:%M:%S",
        help_text="Last login timestamp"
    )
    class Meta:
        model = CustomUser
        fields = ("id","email", "username", "is_active", "date_joined", "last_login")
        read_only_fields = ("id", "email", "is_active", "date_joined", "last_login")


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")

        if email and password:
            user = CustomUser.objects.filter(email=email).first()
            if user:
                if not user.check_password(password):
                    raise serializers.ValidationError(
                        {
                            "password": "The password you entered is incorrect. Please try again."
                        },
                        code="invalid_password",
                    )
            else:
                raise serializers.ValidationError(
                    {
                        "email": "No account was found with this email address. Please sign up first."
                    },
                    code="user_not_found",
                )

        else:
            raise serializers.ValidationError(
                'Both "email" and "password" are required.', code="missing_fields"
            )

        data["user"] = user
        return data


class UserLogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=True)


class UserReactivateSerializer(serializers.Serializer):
    reactivation_token = serializers.CharField(required=True)


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, write_only=True)

    def validate_new_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError(
                "Password must be at least 8 characters long."
            )
        if not any(char.isdigit() for char in value):
            raise serializers.ValidationError(
                "Password must contain at least one number."
            )
        return value


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user
        current_password = attrs.get("current_password")
        new_password = attrs.get("new_password")
        confirm_password = attrs.get("confirm_password")

        if not user.check_password(current_password):
            raise serializers.ValidationError(
                {"current_password": ["current password not matched."]},
                code="invalid_current_password",
            )

        if new_password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": ["New password and confirm password did not match."]},
                code="password_mismatch",
            )

        validate_password(new_password, user=user)
        return attrs


# Profile Prefer Email and Username as read-only fields since they are tied to the user model and should not be changed through the profile endpoint. If you want to allow updates, you can remove the read_only=True and handle the updates in the view.


class ProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        source="user.username", read_only=True, help_text="User's username"
    )
    email = serializers.CharField(
        source="user.email", read_only=True, help_text="User's email address"
    )
    total_points = serializers.SerializerMethodField()
    current_level = serializers.SerializerMethodField()
    goals_completed = serializers.SerializerMethodField()
    current_streak_days = serializers.SerializerMethodField()

    def _get_dynamic_stats(self, obj):
        cache = getattr(self, "_dynamic_stats_cache", {})
        cache_key = str(obj.pk)
        if cache_key in cache:
            return cache[cache_key]

        from goal.models import Goal
        from routine.models import DailyTaskItem, DisciplineStreak

        total_points = int(
            DailyTaskItem.objects.filter(
                task_list__user=obj.user,
                is_completed=True,
            ).aggregate(
                total=Coalesce(
                    Sum("points_earned"),
                    0,
                    output_field=IntegerField(),
                )
            )["total"]
            or 0
        )
        current_level = max(1, (total_points // 100) + 1)
        goals_completed = Goal.objects.filter(user=obj.user, status="completed").count()

        streak, _ = DisciplineStreak.objects.get_or_create(user=obj.user)
        streak.reconcile_with_daily_history(as_of_date=timezone.localdate())
        current_streak_days = int(getattr(streak, "current_streak_days", 0) or 0)

        stats = {
            "total_points": total_points,
            "current_level": current_level,
            "goals_completed": goals_completed,
            "current_streak_days": current_streak_days,
        }
        cache[cache_key] = stats
        self._dynamic_stats_cache = cache
        return stats

    def get_total_points(self, obj):
        return self._get_dynamic_stats(obj)["total_points"]

    def get_current_level(self, obj):
        return self._get_dynamic_stats(obj)["current_level"]

    def get_goals_completed(self, obj):
        return self._get_dynamic_stats(obj)["goals_completed"]

    def get_current_streak_days(self, obj):
        return self._get_dynamic_stats(obj)["current_streak_days"]

    class Meta:
        model = Profile
        fields = [
            "id",
            "username",
            "email",
            "bio",
            "avatar",
            "timezone",
            "subscription_tier",
            "total_points",
            "current_level",
            "goals_completed",
            "current_streak_days",
            "preferred_language",
            "theme",
        ]
        read_only_fields = ["id", "username", "email", "total_points", "current_level"]

        extra_kwargs = {
            "bio": {
                "allow_blank": True,
                "max_length": 300,
                "help_text": "A brief biography of the user (max 300 characters).",
                "error_messages": {
                    "max_length": "Bio cannot exceed 300 characters.",
                },
            },
            "avatar": {
                "allow_null": True,
                "help_text": "The user's avatar image URL (can be null).",
            },
            "timezone": {
                "help_text": "The user's preferred timezone (default is Asia/Kathmandu)."
            },
            "subscription_tier": {
                "help_text": "The user's subscription tier (free, pro_monthly, lifetime)."
            },
            "preferred_language": {
                "help_text": "The user's preferred language (en, hi, nep)."
            },
            "theme": {"help_text": "The user's preferred theme (light, dark)."},
        }
        

class UserPersonalDetailsSerializer(serializers.ModelSerializer):

    class Meta:
        model = UserPersonalDetails
        fields = (
            "id",
            "date_of_birth",
            "current_age",       # computed, read-only
            "current_situation",
            "roadmap_start_date",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at", "current_age")
        
    def validate_date_of_birth(self, value):
        today = timezone.now().date()
        if value >= today:
            raise serializers.ValidationError("Date of birth must be in the past.")
        
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 13 or age > 100:
            raise serializers.ValidationError("Age must be between 13 and 100.")
        
        return value

    def validate_roadmap_start_date(self, value):
        today = timezone.now().date()
        if self.instance is not None:
            if value != self.instance.roadmap_start_date:
                raise serializers.ValidationError(
                    "Roadmap start date cannot be changed once it is set."
                )
            return value

        if value < today:
            raise serializers.ValidationError("Roadmap start date cannot be in the past.")
        return value



class NotificationSettingsSerializer(serializers.ModelSerializer):
    preference_contract = serializers.CharField(
        read_only=True,
        default="preference_only",
        help_text="These fields store user preferences only, not confirmed delivery subscriptions.",
    )

    class Meta:
        model = NotificationSettings
        fields = (
            "id",
            "notifications_enabled",
            "routine_remainders",
            "streak_warnings",
            "personalize_assistant",
            "push_notifications",
            "email_notifications",
            "preference_contract",
        )
