import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CommunityDiscussion",
            fields=[
                ("id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=255)),
                ("content", models.TextField(blank=True)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("general", "General"),
                            ("goals", "Goals"),
                            ("routines", "Routines"),
                            ("habits", "Habits"),
                            ("motivation", "Motivation"),
                            ("achievements", "Achievements"),
                            ("questions", "Questions"),
                        ],
                        default="general",
                        max_length=30,
                    ),
                ),
                ("author_id", models.CharField(default=uuid.uuid4, editable=False, max_length=64)),
                ("author_name", models.CharField(max_length=120)),
                ("author_avatar", models.URLField(blank=True, default="")),
                ("author_role", models.CharField(default="member", max_length=30)),
                ("author_level", models.IntegerField(default=1)),
                ("author_badges", models.IntegerField(default=0)),
                ("author_reputation", models.IntegerField(default=0)),
                ("likes", models.IntegerField(default=0)),
                ("comments", models.IntegerField(default=0)),
                ("views", models.IntegerField(default=0)),
                ("is_pinned", models.BooleanField(default=False)),
                ("is_hot", models.BooleanField(default=False)),
                ("last_activity", models.DateTimeField()),
                ("tags", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "community_discussions",
                "ordering": ["-is_pinned", "-is_hot", "-last_activity", "-created_at"],
                "indexes": [
                    models.Index(fields=["category", "last_activity"], name="community_d_categor_e4f057_idx"),
                    models.Index(fields=["is_pinned", "is_hot"], name="community_d_is_pinn_2f5df6_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CommunityEvent",
            fields=[
                ("id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("meetup", "Meetup"),
                            ("webinar", "Webinar"),
                            ("challenge", "Challenge"),
                            ("workshop", "Workshop"),
                        ],
                        default="meetup",
                        max_length=20,
                    ),
                ),
                ("start_date", models.DateTimeField()),
                ("end_date", models.DateTimeField()),
                ("attendees", models.IntegerField(default=0)),
                ("host_id", models.CharField(default=uuid.uuid4, editable=False, max_length=64)),
                ("host_name", models.CharField(max_length=120)),
                ("host_avatar", models.URLField(blank=True, default="")),
                ("host_role", models.CharField(default="member", max_length=30)),
                ("host_level", models.IntegerField(default=1)),
                ("host_badges", models.IntegerField(default=0)),
                ("host_reputation", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "community_events",
                "ordering": ["start_date"],
            },
        ),
        migrations.CreateModel(
            name="CommunityLeaderboardEntry",
            fields=[
                ("id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("avatar", models.URLField(blank=True, default="")),
                ("level", models.IntegerField(default=1)),
                ("points", models.IntegerField(default=0)),
                ("streak", models.IntegerField(default=0)),
                ("rank", models.IntegerField(default=1)),
                (
                    "change",
                    models.CharField(
                        choices=[("up", "Up"), ("down", "Down"), ("same", "Same")],
                        default="same",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "community_leaderboard_entries",
                "ordering": ["rank", "-points"],
            },
        ),
        migrations.CreateModel(
            name="CommunityTopic",
            fields=[
                ("id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("category", models.CharField(default="general", max_length=30)),
                ("count", models.IntegerField(default=0)),
                (
                    "trend",
                    models.CharField(
                        choices=[("up", "Up"), ("down", "Down"), ("same", "Same")],
                        default="same",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "community_topics",
                "ordering": ["-count", "name"],
            },
        ),
    ]
