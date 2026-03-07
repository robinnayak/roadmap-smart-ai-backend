from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("goal", "0006_commitmentcontract"),
        ("journeybook", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="journeybook",
            name="goals",
            field=models.ManyToManyField(
                blank=True,
                related_name="journey_book_selections",
                to="goal.goal",
            ),
        ),
    ]
