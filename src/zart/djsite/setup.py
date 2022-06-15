'django settings setup'
import os


def setup_settings():
    'Configure django settings module'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'zart.djsite.settings')
