from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('routine', '0013_healthprofile_job_type_other'),
    ]

    operations = [
        migrations.AlterField(
            model_name='healthprofile',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='health_profiles', to='authentication.customuser'),
        ),
    ]
