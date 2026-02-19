from django.apps import AppConfig


class GoalConfig(AppConfig):
    name = 'goal'
    
    def ready(self):
        import goal.signals # Register signals when app is ready