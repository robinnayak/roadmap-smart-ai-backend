from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("routine", "0002_alter_dailytaskitem_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailytaskitem",
            name="time_slot",
            field=models.CharField(
                blank=True,
                choices=[
                    ("morning", "Morning"),
                    ("afternoon", "Afternoon"),
                    ("evening", "Evening"),
                ],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="dailytaskitem",
            index=models.Index(fields=["task_list", "time_slot"], name="dti_tasklist_timeslot_idx"),
        ),
    ]
