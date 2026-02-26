import importlib.util
import logging

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


logger = logging.getLogger(__name__)


class JourneybookConfig(AppConfig):
    name = 'journeybook'

    def ready(self):
        if importlib.util.find_spec("reportlab") is None:
            message = (
                "Journey Book requires ReportLab, but it is not installed in this backend runtime. "
                "Install dependencies with: python -m pip install -r roadmap/requirements.txt"
            )
            logger.critical(message)
            raise ImproperlyConfigured(message)
