# lift_monitor/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('lifts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('api/', include('lifts.api_urls', namespace='lifts_api')),
]

# Add this line at the bottom
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)