from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("authentication", "0001_initial"),
        ("goal", "0005_recalculate_goal_progress"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommitmentContract",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("identity_statement", models.TextField()),
                ("signature_name", models.CharField(max_length=255)),
                ("cc_email", models.EmailField(blank=True, max_length=254, null=True)),
                ("goals_snapshot", models.JSONField(blank=True, default=list)),
                ("deadlines_snapshot", models.JSONField(blank=True, default=list)),
                ("is_signed", models.BooleanField(default=False)),
                ("signed_at", models.DateTimeField(blank=True, null=True)),
                ("pdf_url", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="commitment_contract",
                        to="authentication.customuser",
                    ),
                ),
            ],
            options={
                "db_table": "commitment_contracts",
                "ordering": ["-updated_at"],
            },
        ),
    ]
