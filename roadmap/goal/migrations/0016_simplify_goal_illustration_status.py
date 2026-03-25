from django.db import migrations, models


def normalize_goal_illustration_status(apps, schema_editor):
    Goal = apps.get_model("goal", "Goal")

    Goal.objects.filter(illustration_status__in=["generating", "failed"]).update(
        illustration_status="pending"
    )
    Goal.objects.filter(illustration_status="done", illustration_url__isnull=True).update(
        illustration_status="pending"
    )
    Goal.objects.filter(illustration_status="done", illustration_url="").update(
        illustration_status="pending"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0015_goal_illustration_fields"),
    ]

    operations = [
        migrations.RunPython(normalize_goal_illustration_status, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="goal",
            name="illustration_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("done", "Done"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
