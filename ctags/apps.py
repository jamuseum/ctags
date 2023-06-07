"""
App for canonical tagging.
"""
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TaggingConfig(AppConfig):
    """
    Config for Tagging application.
    """
    name = 'ctags'
    label = 'ctags'
    verbose_name = _('Canonical Tags')
