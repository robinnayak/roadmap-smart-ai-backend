from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager, PermissionsMixin
import uuid
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

# Create your models here.

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=30, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-date_joined"]


class Profile(models.Model):
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="profile"
    )

    SUBSCRIPTION_CHOICES = [
        ("free", "Free"),
        ("pro_monthly", "Pro Monthly"),
        ("lifetime", "Lifetime"),
    ]

    LANGUAGE_CHOICES = [("en", "English"), ("hi", "Hindi"), ("nep", "Nepal")]

    THEME_CHOICES = [("light", "Light"), ("dark", "dark")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bio = models.TextField(
        blank=True, null=True, default="As an expert in AI application integration..."
    )
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    timezone = models.CharField(max_length=50, default="UTC")
    subscription_tier = models.CharField(
        max_length=20, choices=SUBSCRIPTION_CHOICES, default="free"
    )

    subscription_start_date = models.DateTimeField(null=True, blank=True)
    subscription_end_date = models.DateTimeField(null=True, blank=True)

    # Gamification
    total_points = models.IntegerField(default=0)
    current_level = models.IntegerField(default=1)

    # Preferences
    preferred_language = models.CharField(
        max_length=10, choices=LANGUAGE_CHOICES, default="en"
    )
    theme = models.CharField(max_length=20, choices=THEME_CHOICES ,default="light")

    last_active = models.DateTimeField(auto_now=True)
    days_active = models.IntegerField(default=0)

    def __str__(self):
        return f"Profile of {self.user.email}"

class UserPersonalDetails(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='user_personal_details'
    )
    current_age = models.IntegerField(
        validators=[MinValueValidator(13), MaxValueValidator(100)],
        help_text="Current age",
        default=0
    )
    
    target_age = models.IntegerField(
        validators=[MinValueValidator(14), MaxValueValidator(120)],
        help_text="Age by which you want to achieve your goals",
        default=0
    )
    roadmap_start_date = models.DateField(
        default=timezone.now,
        help_text="When to start the roadmap (usually today)"
    )
    current_situation = models.TextField(
        help_text="""
        Describe your current situation:
        - What are you doing now? (student, employed, unemployed, etc.)
        - Where are you? (location, life stage)
        - What's your current state? (skills, resources, constraints)
        
        Example: "I'm a 25-year-old software developer in Nepal, earning $800/month. 
        I want to study Master's in AI in Australia and become a senior ML engineer. 
        I have basic Python skills but need to learn advanced ML. Limited budget but 
        strong family support."
        """
    )
    
    is_created = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        if not self.is_created:
            self.is_created = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email}'s will be successful at the age of (v{self.target_age})"

class NotificationSettings(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='notification_settings'
    )
    
    #master toggle 
    notifications_enabled = models.BooleanField(default=True)
    
    #Notification Types
    routine_remainders = models.BooleanField(default=True)
    streak_warnings = models.BooleanField(default=True)
    
    #AI personalize assistant
    personalize_assistant = models.BooleanField(default=True)
    
    #channels
    push_notifications = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.user.email}'s Notfication settings"
    
    
    
    
