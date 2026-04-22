from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0002_alter_goal_primary_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="how_it_helps_you",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="how_to_do_it",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="why_this",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="your_log_placeholder",
            field=models.TextField(blank=True, null=True),
        ),
    ]
