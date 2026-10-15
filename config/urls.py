from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Prumo · Administração"
admin.site.site_title = "Prumo"
admin.site.index_title = "Usuários e obras"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("conta/", include("django.contrib.auth.urls")),
    path("", include("obras.urls")),
]
