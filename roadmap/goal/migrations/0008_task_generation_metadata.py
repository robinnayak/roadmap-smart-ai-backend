from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("goal", "0007_goal_financial_current_saved_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="difficulty_level",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="task",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("daily", "Daily"),
                    ("weekdays", "Weekdays"),
                    ("3x_per_week", "3x per week"),
                    ("2x_per_week", "2x per week"),
                    ("weekly", "Weekly"),
                    ("monthly", "Monthly"),
                    ("event_triggered", "Event Triggered"),
                    ("once", "Once"),
                ],
                default="once",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="is_prerequisite",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="task",
            name="item_type",
            field=models.CharField(
                choices=[
                    ("physical", "Physical"),
                    ("cognitive", "Cognitive"),
                    ("habit", "Habit"),
                    ("ritual", "Ritual"),
                    ("task", "Task"),
                ],
                default="task",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="rationale",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="task",
            name="sequence_position",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task",
            name="session_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("new_content", "New Content"),
                    ("practice", "Practice"),
                    ("review", "Review"),
                    ("test", "Test"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="trigger_after_days",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
