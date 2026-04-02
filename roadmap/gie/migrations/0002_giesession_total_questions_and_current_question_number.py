from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gie", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="giesession",
            name="current_question_number",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="giesession",
            name="total_questions",
            field=models.PositiveIntegerField(default=5),
        ),
    ]
