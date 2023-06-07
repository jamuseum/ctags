"""
Custom managers for tagging.
"""
from django.contrib.contenttypes.models import ContentType
from django.db import models

from ctags.models import CTag
from ctags.models import CTaggedItem


class ModelTagManager(models.Manager):
    """
    A manager for retrieving tags for a particular model.
    """
    def get_queryset(self):
        ctype = ContentType.objects.get_for_model(self.model)
        return CTag.objects.filter(
            items__content_type__pk=ctype.pk).distinct()

    def cloud(self, *args, **kwargs):
        return CTag.objects.cloud_for_model(self.model, *args, **kwargs)

    def related(self, tags, *args, **kwargs):
        return CTag.objects.related_for_model(tags, self.model, *args, **kwargs)

    def usage(self, *args, **kwargs):
        return CTag.objects.usage_for_model(self.model, *args, **kwargs)


class ModelTaggedItemManager(models.Manager):
    """
    A manager for retrieving model instances based on their tags.
    """
    def related_to(self, obj, queryset=None, num=None):
        if queryset is None:
            return CTaggedItem.objects.get_related(obj, self.model, num=num)
        else:
            return CTaggedItem.objects.get_related(obj, queryset, num=num)

    def with_all(self, tags, queryset=None):
        if queryset is None:
            return CTaggedItem.objects.get_by_model(self.model, tags)
        else:
            return CTaggedItem.objects.get_by_model(queryset, tags)

    def with_any(self, tags, queryset=None):
        if queryset is None:
            return CTaggedItem.objects.get_union_by_model(self.model, tags)
        else:
            return CTaggedItem.objects.get_union_by_model(queryset, tags)


class TagDescriptor(object):
    """
    A descriptor which provides access to a ``ModelTagManager`` for
    model classes and simple retrieval, updating and deletion of tags
    for model instances.
    """
    def __get__(self, instance, owner):
        if not instance:
            tag_manager = ModelTagManager()
            tag_manager.model = owner
            return tag_manager
        else:
            return CTag.objects.get_for_object(instance)

    def __set__(self, instance, value):
        CTag.objects.update_tags(instance, value)

    def __delete__(self, instance):
        CTag.objects.update_tags(instance, None)
