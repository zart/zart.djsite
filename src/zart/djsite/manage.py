#!/usr/bin/env python
'django command-line utility for administrative tasks'
import warnings
from zart.djsite.setup import setup_settings


def _fix_argv():
    'hack to fix runserver'
    import sys, __main__, zart.djsite.manage

    sys.argv[0], __main__.__spec__ = zart.djsite.manage.__file__, None


def main():
    'Run administrative tasks'
    _fix_argv()
    setup_settings()
    try:
        from django.core.management import execute_from_command_line
    except ImportError:
        warnings.warn(
            "Couldn't import Django. Are you sure it's installed and "
            'available on your PYTHONPATH environment variable? Did you '
            'forget to activate a virtual environment?'
        )
        raise
    execute_from_command_line()


if __name__ == '__main__':
    main()
