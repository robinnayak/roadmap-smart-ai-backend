from django.db import migrations


def recalculate_goal_progress(apps, schema_editor):
    Goal = apps.get_model("goal", "Goal")
    Milestone = apps.get_model("goal", "Milestone")

    for goal in Goal.objects.all():
        milestones = Milestone.objects.filter(goal=goal)
        if not milestones.exists():
            continue

        total = milestones.count()
        total_progress = sum((m.progress_percentage or 0) for m in milestones)
        progress = int(total_progress / total) if total else 0

        if progress == 100:
            status = "completed"
        elif progress > 0:
            status = "in_progress"
        elif goal.status == "completed":
            status = "not_started"
        else:
            status = goal.status

        Goal.objects.filter(pk=goal.pk).update(progress_percentage=progress, status=status)


def reverse_recalculate_goal_progress(apps, schema_editor):
    # No safe reverse; keep current values.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0004_task_preferred_time_slot"),
    ]

    operations = [
        migrations.RunPython(recalculate_goal_progress, reverse_recalculate_goal_progress),
    ]

