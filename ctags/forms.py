"""
Form components for tagging.
"""
from django import forms
from django.utils.translation import gettext as _

from ctags import settings
from ctags.models import CTag
from ctags.utils import parse_tag_input


class TagAdminForm(forms.ModelForm):
    class Meta:
        model = CTag
        fields = ('approved_en', 'name_en',
                  'approved_ja', 'name_ja',
                  'approved_es', 'name_es',
                  'approved_pt', 'name_pt',)


class TagField(forms.CharField):
    """
    A ``CharField`` which validates that its input is a valid list of
    tag names.
    """
    def clean(self, value):
        value = super(TagField, self).clean(value)
        if len(value) > settings.MAX_TAG_LENGTH:
            raise forms.ValidationError(
                _('Each tag may be no more than %s characters long.') %
                settings.MAX_TAG_LENGTH)
        return value
