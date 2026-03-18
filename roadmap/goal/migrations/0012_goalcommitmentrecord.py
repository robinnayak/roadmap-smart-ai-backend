from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0011_goal_timeline_insight_cache"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GoalCommitmentRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("accepted_at", models.DateTimeField(auto_now_add=True)),
                ("commitment_intent", models.TextField()),
                ("commitment_effort", models.TextField()),
                ("commitment_responsibility", models.TextField()),
                ("signed_name", models.CharField(max_length=255)),
                ("signed_at", models.DateTimeField()),
                ("contract_snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "goal",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="commitment_record",
                        to="goal.goal",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="goal_commitment_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "goal_commitment_records",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="goalcommitmentrecord",
            index=models.Index(fields=["user", "accepted_at"], name="goal_commitm_user_id_ef18db_idx"),
        ),
    ]
