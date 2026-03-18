from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0010_goal_primary_category_15_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="goal",
            name="timeline_insight_fingerprint",
            field=models.CharField(
                blank=True,
                help_text="Hash of the inputs used to generate the cached timeline insight.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="goal",
            name="timeline_insight_generated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the cached timeline insight was last generated.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="goal",
            name="timeline_insight_payload",
            field=models.JSONField(
                blank=True,
                help_text="Cached read-only timeline insight payload for this goal.",
                null=True,
            ),
        ),
    ]
