from django.apps import AppConfig


class GoalConfig(AppConfig):
    name = 'goal'
    
    def ready(self):
        import goal.signals # noqa