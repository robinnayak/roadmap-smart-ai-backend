from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("routine", "0017_wakeinteraction_wakebaselinestate"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailytaskitem",
            name="removed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dailytaskitem",
            name="removed_by_user",
            field=models.BooleanField(default=False),
        ),
    ]
