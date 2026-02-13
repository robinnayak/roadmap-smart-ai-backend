
from django.urls import path
from .views import BaseProjectMessageApiView

urlpatterns = [
    path('', BaseProjectMessageApiView.as_view(), name='base-message'),
]
