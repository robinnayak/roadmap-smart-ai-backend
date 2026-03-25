
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from journeybook.views import JourneyBookDemoPreviewAPIView, JourneyBookDemoPreviewPDFAPIView


def build_urlpatterns(*, debug: bool):
    urlpatterns = [
        path('admin/', admin.site.urls),
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
        path('', include('base.urls')),
    ]

    # Product auth is JWT under /auth/. The DRF session login/logout routes are
    # debug-only tooling for the browsable API and are not a supported app auth flow.
    if debug:
        urlpatterns.insert(1, path('api-auth/', include('rest_framework.urls')))
    return urlpatterns


urlpatterns = build_urlpatterns(debug=settings.DEBUG)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
