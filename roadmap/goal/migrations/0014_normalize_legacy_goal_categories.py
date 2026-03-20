from django.db import migrations


LEGACY_CATEGORY_MAP = {
    "financial": "finance",
    "health": "fitness",
    "personal": "productivity",
}


def normalize_legacy_categories(apps, schema_editor):
    Goal = apps.get_model("goal", "Goal")
    for legacy_value, canonical_value in LEGACY_CATEGORY_MAP.items():
        Goal.objects.filter(primary_category=legacy_value).update(primary_category=canonical_value)


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0013_rename_goal_commitm_user_id_ef18db_idx_goal_commit_user_id_ba780e_idx"),
    ]

    operations = [
        migrations.RunPython(normalize_legacy_categories, migrations.RunPython.noop),
    ]
