#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    import platform
    platform._wmi_query = lambda *args, **kwargs: ('10', '1', '1', '1', '0')
    try:
        platform.win32_ver = lambda *args, **kwargs: ('10', '10.0.19041', '', 'Multiprocessor Free')
    except Exception:
        pass
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'roadmap.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
