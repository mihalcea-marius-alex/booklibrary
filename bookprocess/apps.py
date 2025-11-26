"""Django application configuration for the ``bookprocess`` app.

This module exposes the :class:`BookprocessConfig` AppConfig used to
register application metadata with Django.
"""

from django.apps import AppConfig


class BookprocessConfig(AppConfig):
    """Application configuration for the ``bookprocess`` Django app. """
    default_auto_field = 'django.db.models.BigAutoField' #: The default type for automatically generated primary key fields.
    name = 'bookprocess' #: The Python path to the application package. Django uses this to look up the module.
