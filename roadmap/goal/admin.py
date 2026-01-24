from django.contrib import admin
from .models import UserCurrentSituationGoal, Goal, GoalAttributes, Milestone, SubGoal, Task

# Register your models here.

admin.site.register(UserCurrentSituationGoal)
admin.site.register(Goal)
admin.site.register(GoalAttributes)
admin.site.register(Milestone)
admin.site.register(SubGoal)
admin.site.register(Task) 


