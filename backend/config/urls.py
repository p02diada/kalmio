"""Root URLs for Kalmio."""

from api.ninja import api
from django.conf import settings
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("api/", api.urls),
]

if settings.KALMIO_ENABLE_ADMIN:
    urlpatterns.append(path(settings.KALMIO_ADMIN_PATH, admin.site.urls))
