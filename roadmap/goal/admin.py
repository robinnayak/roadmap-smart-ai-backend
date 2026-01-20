from django.contrib import admin
from .models import UserCurrentSituationGoal, Goal, GoalAttributes
# Register your models here.

admin.site.register(UserCurrentSituationGoal)
admin.site.register(Goal)
admin.site.register(GoalAttributes)
