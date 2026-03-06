import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("routine", "0004_rename_dti_tasklist_timeslot_idx_daily_task__task_li_0f6cf5_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdaptiveRoadmapState",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("current_scale_level", models.IntegerField(default=0)),
                ("consecutive_miss_days", models.IntegerField(default=0)),
                ("consecutive_success_days", models.IntegerField(default=0)),
                ("weekly_miss_days", models.IntegerField(default=0)),
                ("last_evaluated_date", models.DateField(blank=True, null=True)),
                ("last_scale_change_date", models.DateField(blank=True, null=True)),
                ("weekly_reset_anchor", models.DateField(blank=True, null=True)),
                ("last_sunday_rebuild_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="adaptive_roadmap_state",
                        to="authentication.customuser",
                    ),
                ),
            ],
            options={
                "db_table": "adaptive_roadmap_states",
            },
        ),
    ]
