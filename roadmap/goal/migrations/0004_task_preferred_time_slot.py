from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0003_alter_goal_why_it_matters"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="preferred_time_slot",
            field=models.CharField(
                blank=True,
                choices=[
                    ("morning", "Morning"),
                    ("afternoon", "Afternoon"),
                    ("evening", "Evening"),
                ],
                max_length=10,
                null=True,
                help_text="Preferred time window for this task: morning/afternoon/evening.",
            ),
        ),
    ]

