from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("routine", "0002_points_wallet_rewards"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailytaskitem",
            name="how_it_helps_you",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dailytaskitem",
            name="how_to_do_it",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dailytaskitem",
            name="your_log_placeholder",
            field=models.TextField(blank=True, null=True),
        ),
    ]
