import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def seed_reward_catalog(apps, schema_editor):
    RewardCatalogItem = apps.get_model("routine", "RewardCatalogItem")
    rewards = [
        {
            "slug": "focus-theme-pack",
            "name": "Focus Theme Pack",
            "description": "Placeholder cosmetic reward for unlocking an alternate focus theme.",
            "cost": Decimal("25.0000"),
        },
        {
            "slug": "streak-freeze",
            "name": "Streak Freeze",
            "description": "Placeholder reward that can later protect a streak for one missed day.",
            "cost": Decimal("40.0000"),
        },
        {
            "slug": "insight-badge",
            "name": "Insight Badge",
            "description": "Placeholder profile badge reward for demo redemption flows.",
            "cost": Decimal("60.0000"),
        },
    ]
    for reward in rewards:
        RewardCatalogItem.objects.update_or_create(slug=reward["slug"], defaults=reward)


def unseed_reward_catalog(apps, schema_editor):
    RewardCatalogItem = apps.get_model("routine", "RewardCatalogItem")
    RewardCatalogItem.objects.filter(
        slug__in=["focus-theme-pack", "streak-freeze", "insight-badge"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("routine", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailytaskitem",
            name="base_points",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("15.0000"),
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(Decimal("0.0000"))],
            ),
        ),
        migrations.CreateModel(
            name="PointsWallet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("current_balance", models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=14)),
                ("lifetime_earned", models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="points_wallet",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "points_wallets",
            },
        ),
        migrations.CreateModel(
            name="RewardCatalogItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                (
                    "cost",
                    models.DecimalField(
                        decimal_places=4,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.0000"))],
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "reward_catalog_items",
                "ordering": ["cost", "name"],
            },
        ),
        migrations.CreateModel(
            name="PointsTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("transaction_type", models.CharField(choices=[("credit", "Credit"), ("debit", "Debit")], max_length=10)),
                ("amount", models.DecimalField(decimal_places=4, max_digits=14)),
                (
                    "source_type",
                    models.CharField(
                        choices=[("task_completion", "Task Completion"), ("redemption", "Redemption")],
                        max_length=30,
                    ),
                ),
                ("note", models.CharField(max_length=255)),
                ("balance_after", models.DecimalField(decimal_places=4, max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "reward",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="redemption_transactions",
                        to="routine.rewardcatalogitem",
                    ),
                ),
                (
                    "task_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="wallet_transactions",
                        to="routine.dailytaskitem",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transactions",
                        to="routine.pointswallet",
                    ),
                ),
            ],
            options={
                "db_table": "points_transactions",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="pointstransaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(task_item__isnull=False),
                fields=("task_item", "source_type"),
                name="unique_task_completion_points_transaction",
            ),
        ),
        migrations.RunPython(seed_reward_catalog, unseed_reward_catalog),
    ]
