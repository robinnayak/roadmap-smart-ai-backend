from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0014_normalize_legacy_goal_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="goal",
            name="illustration_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="goal",
            name="illustration_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("generating", "Generating"),
                    ("done", "Done"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="goal",
            name="illustration_url",
            field=models.URLField(blank=True, null=True),
        ),
    ]
