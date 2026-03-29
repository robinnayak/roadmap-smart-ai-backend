from datetime import time

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserRitualProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ritual_tone", models.CharField(choices=[("bro", "Bro"), ("gentle", "Gentle"), ("soft_girl", "Soft Girl"), ("coach", "Coach")], default="gentle", max_length=20)),
                ("morning_alarm_time", models.TimeField(default=time(6, 15))),
                ("night_alarm_time", models.TimeField(default=time(22, 0))),
                ("date_of_birth", models.DateField(blank=True, null=True)),
                ("ritual_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ritual_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["user_id"],
            },
        ),
        migrations.CreateModel(
            name="DailyRitualLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True, default=django.utils.timezone.localdate)),
                ("shown_variants", models.JSONField(blank=True, default=dict)),
                ("night_session_completed", models.BooleanField(default=False)),
                ("night_session_time", models.TimeField(blank=True, null=True)),
                ("yesterday_task_reflection", models.CharField(blank=True, choices=[("done", "Done"), ("partial", "Partial"), ("missed", "Missed")], max_length=20, null=True)),
                ("tomorrow_intent", models.TextField(blank=True, null=True)),
                ("night_mood", models.CharField(blank=True, choices=[("strong", "Strong"), ("okay", "Okay"), ("rough", "Rough")], max_length=20, null=True)),
                ("morning_session_completed", models.BooleanField(default=False)),
                ("morning_session_time", models.TimeField(blank=True, null=True)),
                ("actual_wake_time", models.TimeField(blank=True, null=True)),
                ("snooze_count", models.IntegerField(default=0)),
                ("morning_energy", models.CharField(blank=True, choices=[("sleepy", "Sleepy"), ("neutral", "Neutral"), ("energized", "Energized"), ("fired", "Fired Up")], max_length=20, null=True)),
                ("wake_delta_minutes", models.IntegerField(blank=True, null=True)),
                ("ritual_streak_day", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="daily_ritual_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-date", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="dailyrituallog",
            index=models.Index(fields=["user", "date"], name="rituals_dai_user_id_64de7e_idx"),
        ),
        migrations.AddConstraint(
            model_name="dailyrituallog",
            constraint=models.UniqueConstraint(fields=("user", "date"), name="unique_daily_ritual_log"),
        ),
    ]
