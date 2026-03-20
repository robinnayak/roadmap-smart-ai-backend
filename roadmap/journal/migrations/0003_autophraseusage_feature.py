from django.db import migrations, models


def split_existing_usage_by_feature(apps, schema_editor):
    AutoPhraseUsage = apps.get_model("journal", "AutoPhraseUsage")
    for usage in AutoPhraseUsage.objects.filter(feature=""):
        usage.feature = "auto_phrase"
        usage.save(update_fields=["feature"])


class Migration(migrations.Migration):

    dependencies = [
        ("journal", "0002_journalentry_full_day_input_journalentry_parsed_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="autophraseusage",
            name="feature",
            field=models.CharField(
                choices=[("auto_phrase", "Auto Phrase"), ("summary_refine", "Summary Refine")],
                default="auto_phrase",
                max_length=30,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(split_existing_usage_by_feature, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="autophraseusage",
            name="unique_user_autophrase_usage_date",
        ),
        migrations.AddConstraint(
            model_name="autophraseusage",
            constraint=models.UniqueConstraint(
                fields=("user", "usage_date", "feature"),
                name="unique_user_autophrase_usage_feature_date",
            ),
        ),
        migrations.AddIndex(
            model_name="autophraseusage",
            index=models.Index(fields=["user", "usage_date", "feature"], name="journal_aut_user_id_eb5b8d_idx"),
        ),
    ]
