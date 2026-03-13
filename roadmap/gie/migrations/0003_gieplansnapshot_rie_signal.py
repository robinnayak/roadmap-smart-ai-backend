from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gie", "0002_gieadaptationproposal"),
    ]

    operations = [
        migrations.AddField(
            model_name="gieplansnapshot",
            name="rie_signal",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
