from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0002_align_userpersonaldetails_schema"),
    ]

    operations = [
        migrations.CreateModel(
            name="MagicLinkToken",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
