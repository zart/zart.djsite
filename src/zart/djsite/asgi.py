'django asgi callable'
from django.core.asgi import get_asgi_application
from .setup import setup_settings

setup_settings()
application = get_asgi_application()
