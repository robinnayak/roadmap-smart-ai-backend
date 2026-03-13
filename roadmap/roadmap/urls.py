
from django.contrib import admin
from django.urls import path, include
from journeybook.views import JourneyBookDemoPreviewAPIView, JourneyBookDemoPreviewPDFAPIView


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api-auth/', include('rest_framework.urls')),
    path('auth/', include('authentication.urls')),
    path('ai/', include('ai.urls')),
    path('gie/', include(('gie.urls', 'gie'), namespace='gie')),
    path('goal/', include('goal.urls')),
    path('routines/', include('routine.urls')),
    path('journal/', include('journal.urls')),
    path('community/', include('community.urls')),
    path('events/', include('events.urls')),
    path('api/journeybook/', include('journeybook.urls', namespace='journeybook')),
    path('journey-books/demo-preview/', JourneyBookDemoPreviewAPIView.as_view(), name='journeybook-demo-preview'),
    path('journey-books/demo-preview/pdf/', JourneyBookDemoPreviewPDFAPIView.as_view(), name='journeybook-demo-preview-pdf'),
    path('', include('base.urls'))
]
