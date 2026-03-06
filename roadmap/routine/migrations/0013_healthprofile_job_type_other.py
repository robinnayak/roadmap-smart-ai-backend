from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('routine', '0012_dailybrief'),
    ]

    operations = [
        migrations.AddField(
            model_name='healthprofile',
            name='job_type_other',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name='healthprofile',
            name='job_type',
            field=models.CharField(blank=True, choices=[('desk', 'Desk/Office'), ('physical', 'Physical/Field'), ('creative', 'Creative'), ('healthcare', 'Healthcare'), ('student', 'Student'), ('freelance', 'Freelance'), ('other', 'Other')], max_length=20),
        ),
    ]
