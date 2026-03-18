from django.db import migrations, models
import re


GOAL_CATEGORIES = (
    "business",
    "fitness",
    "learning",
    "wellness",
    "creative",
    "nutrition",
    "productivity",
    "travel",
    "digital_habits",
    "spiritual",
    "relationships",
    "education",
    "career",
    "finance",
    "parenting",
)

CATEGORY_CHOICES = [(category, category.replace("_", " ").title()) for category in GOAL_CATEGORIES]
TOKEN_PATTERN = re.compile(r"\b[\w']+\b")

CATEGORY_SIGNALS = {
    "business": ["mvp", "launch", "startup", "revenue", "customers", "product", "saas", "users"],
    "fitness": ["run", "marathon", "gym", "workout", "training", "race", "half marathon"],
    "learning": ["learn", "course", "certification", "study", "skill", "machine learning"],
    "wellness": ["stress", "anxiety", "sleep", "therapy", "burnout", "mindfulness"],
    "creative": ["write", "novel", "music", "art", "design", "photography", "podcast"],
    "nutrition": ["diet", "meal prep", "protein", "food", "nutrition", "macro"],
    "productivity": ["focus", "productivity", "routine", "system", "time management"],
    "travel": ["trip", "travel", "flight", "holiday", "itinerary"],
    "digital_habits": ["screen time", "social media", "instagram", "scroll", "digital"],
    "spiritual": ["prayer", "faith", "gratitude", "spiritual", "meaning"],
    "relationships": ["partner", "family", "communication", "friendship", "relationship"],
    "education": ["degree", "university", "thesis", "semester", "phd", "masters", "master's"],
    "career": ["job", "promotion", "salary", "interview", "linkedin", "portfolio", "career"],
    "finance": ["save", "debt", "invest", "budget", "money", "fund", "financial", "emergency fund"],
    "parenting": ["parenting", "kids", "children", "child", "daughter", "son"],
}


def _classify(title: str, description: str, current_category: str) -> str:
    text = f"{title or ''} {description or ''}".lower()
    if current_category == "financial":
        return "finance"
    if current_category == "career":
        if any(word in text for word in CATEGORY_SIGNALS["business"]):
            return "business"
        return "career"
    if current_category == "health":
        if any(word in text for word in CATEGORY_SIGNALS["nutrition"]):
            return "nutrition"
        return "fitness"

    token_set = set(TOKEN_PATTERN.findall(text))
    scores = {}
    for category, keywords in CATEGORY_SIGNALS.items():
        score = 0
        for keyword in keywords:
            if " " in keyword:
                if keyword in text:
                    score += 1
            elif keyword in token_set:
                score += 1
        scores[category] = score
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "productivity"


def forward(apps, schema_editor):
    Goal = apps.get_model("goal", "Goal")
    for goal in Goal.objects.all().iterator():
        goal.primary_category = _classify(goal.title, goal.description or "", goal.primary_category or "")
        goal.save(update_fields=["primary_category", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("goal", "0009_task_new_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="goal",
            name="primary_category",
            field=models.CharField(choices=CATEGORY_CHOICES, max_length=50),
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
