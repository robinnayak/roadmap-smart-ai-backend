from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0003_magiclinktoken"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoginOTPToken",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("code_hash", models.CharField(db_index=True, max_length=64)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
