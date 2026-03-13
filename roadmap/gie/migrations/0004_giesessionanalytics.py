from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("gie", "0003_gieplansnapshot_rie_signal"),
    ]

    operations = [
        migrations.CreateModel(
            name="GIESessionAnalytics",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("turn_count", models.PositiveIntegerField(default=0)),
                ("turns_to_ready_to_finalize", models.PositiveIntegerField(blank=True, null=True)),
                ("time_to_ready_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("time_to_finalize_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("schema_completeness_progress", models.JSONField(blank=True, default=list)),
                ("plan_review_entered", models.BooleanField(default=False)),
                ("plan_accepted", models.BooleanField(default=False)),
                ("finalize_attempt_count", models.PositiveIntegerField(default=0)),
                ("finalize_success_count", models.PositiveIntegerField(default=0)),
                ("adaptation_request_count", models.PositiveIntegerField(default=0)),
                ("fallback_activation_count", models.PositiveIntegerField(default=0)),
                ("degradation_event_count", models.PositiveIntegerField(default=0)),
                ("last_fallback_reason_code", models.CharField(blank=True, max_length=120, null=True)),
                (
                    "last_stage",
                    models.CharField(
                        choices=[
                            ("intake", "Intake"),
                            ("question_loop", "Question Loop"),
                            ("review", "Review"),
                            ("finalized", "Finalized"),
                            ("adaptation", "Adaptation"),
                            ("fallback", "Fallback"),
                            ("blocked", "Blocked"),
                        ],
                        default="intake",
                        max_length=32,
                    ),
                ),
                (
                    "drop_off_stage",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("intake", "Intake"),
                            ("question_loop", "Question Loop"),
                            ("review", "Review"),
                            ("finalized", "Finalized"),
                            ("adaptation", "Adaptation"),
                            ("fallback", "Fallback"),
                            ("blocked", "Blocked"),
                        ],
                        max_length=32,
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "session",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analytics",
                        to="gie.giesession",
                    ),
                ),
            ],
            options={
                "db_table": "gie_session_analytics",
            },
        ),
        migrations.AddIndex(
            model_name="giesessionanalytics",
            index=models.Index(fields=["plan_accepted"], name="gie_sessio_plan_ac_1efa3a_idx"),
        ),
        migrations.AddIndex(
            model_name="giesessionanalytics",
            index=models.Index(fields=["last_stage"], name="gie_sessio_last_st_89cebe_idx"),
        ),
        migrations.AddIndex(
            model_name="giesessionanalytics",
            index=models.Index(fields=["drop_off_stage"], name="gie_sessio_drop_of_8f87ce_idx"),
        ),
        migrations.AddIndex(
            model_name="giesessionanalytics",
            index=models.Index(fields=["created_at"], name="gie_sessio_created_9f6d4e_idx"),
        ),
    ]
