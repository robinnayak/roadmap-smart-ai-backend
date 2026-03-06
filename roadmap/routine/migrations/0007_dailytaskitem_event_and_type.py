from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0001_initial"),
        ("routine", "0006_dailytasklist_schedule_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailytaskitem",
            name="event",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="daily_items",
                to="events.event",
            ),
        ),
        migrations.AlterField(
            model_name="dailytaskitem",
            name="item_type",
            field=models.CharField(
                choices=[
                    ("habit", "Daily Habit"),
                    ("goal_task", "Goal Task"),
                    ("event", "Event"),
                ],
                max_length=15,
            ),
        ),
    ]
