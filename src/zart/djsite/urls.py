'django routing'
from django.contrib import admin

try:
    from django.urls import include, re_path
except ImportError:
    from django.conf.urls import include, url as re_path


urlpatterns = [
    re_path(r'^admin/', admin.site.urls),
]
