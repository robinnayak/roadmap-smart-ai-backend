
from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api-auth/', include('rest_framework.urls')),
    path('auth/', include('authentication.urls')),
    path('ai/', include('ai.urls')),
    path('goal/', include('goal.urls')),
    path('routines/', include('routine.urls')),
    path('', include('base.urls'))
]
