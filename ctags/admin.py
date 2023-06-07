"""
Admin components for tagging.
"""
from django.contrib import admin

from ctags.forms import TagAdminForm
from ctags.models import CTag
from ctags.models import CTaggedItem


class TagAdmin(admin.ModelAdmin):
    fieldsets = (
        (None, {'fields': ('approved_en', 'name_en')}),
        (None, {'fields': ('approved_ja', 'name_ja')}),
        (None, {'fields': ('approved_es', 'name_es')}),
        (None, {'fields': ('approved_pt', 'name_pt')}),
    )
    list_display = (
        'approved_en', 'name_en',
        'approved_ja', 'name_ja',
        'approved_es', 'name_es',
        'approved_pt', 'name_pt',
    )
    list_display_links = None
    list_editable = (
        'approved_en', 'name_en',
        'approved_ja', 'name_ja',
        'approved_es', 'name_es',
        'approved_pt', 'name_pt',
    )
    list_per_page = 100
    save_on_top = True


#admin.site.register(CTaggedItem)
admin.site.register(CTag, TagAdmin)
