from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('routine', '0014_healthprofile_multi_per_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='habitrecommendation',
            name='source_health_profile',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='habit_recommendations', to='routine.healthprofile'),
        ),
    ]
