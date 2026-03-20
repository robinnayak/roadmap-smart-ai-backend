from django.db import migrations, models


def backfill_wave_4a_state(apps, schema_editor):
    HealthProfile = apps.get_model("routine", "HealthProfile")
    DailyTaskItem = apps.get_model("routine", "DailyTaskItem")

    user_ids = list(
        HealthProfile.objects.order_by("user_id").values_list("user_id", flat=True).distinct()
    )
    for user_id in user_ids:
        profiles = list(
            HealthProfile.objects.filter(user_id=user_id).order_by("-updated_at", "-created_at", "-id")
        )
        active_profile_id = profiles[0].id if profiles else None
        for profile in profiles:
            should_be_active = profile.id == active_profile_id
            if profile.is_active != should_be_active:
                profile.is_active = should_be_active
                profile.save(update_fields=["is_active", "updated_at"])

    DailyTaskItem.objects.filter(
        item_type="goal_task",
        goal_task__isnull=True,
    ).update(item_type="manual_task")


class Migration(migrations.Migration):

    dependencies = [
        ("routine", "0019_habittracker_is_deletable_habittracker_is_system_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailytaskitem",
            name="occurrence_id",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="healthprofile",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="dailytaskitem",
            name="item_type",
            field=models.CharField(
                choices=[
                    ("habit", "Daily Habit"),
                    ("goal_task", "Goal Task"),
                    ("manual_task", "Manual Task"),
                    ("event", "Event"),
                    ("journal", "Journal"),
                ],
                max_length=15,
            ),
        ),
        migrations.RunPython(backfill_wave_4a_state, migrations.RunPython.noop),
    ]
