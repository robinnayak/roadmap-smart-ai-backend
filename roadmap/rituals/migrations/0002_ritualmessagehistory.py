from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("rituals", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RitualMessageHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("trigger_type", models.CharField(max_length=40)),
                ("template_id", models.CharField(max_length=80)),
                ("message", models.TextField()),
                (
                    "tone",
                    models.CharField(
                        choices=[("bro", "Bro"), ("gentle", "Gentle"), ("soft_girl", "Soft Girl"), ("coach", "Coach")],
                        max_length=20,
                    ),
                ),
                ("shown_on", models.DateField(db_index=True, default=django.utils.timezone.localdate)),
                ("shown_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ritual_message_history",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-shown_at"],
            },
        ),
        migrations.AddIndex(
            model_name="ritualmessagehistory",
            index=models.Index(fields=["user", "trigger_type", "shown_at"], name="rituals_rit_user_id_15f1e5_idx"),
        ),
        migrations.AddIndex(
            model_name="ritualmessagehistory",
            index=models.Index(fields=["user", "template_id"], name="rituals_rit_user_id_3bd597_idx"),
        ),
    ]
