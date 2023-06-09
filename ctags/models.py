"""
Models and managers for tagging.
"""
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db import models
from django.db.models.functions import Lower
from django.db.models.query_utils import Q
#from django.db.utils import IntegrityError
from django.utils.encoding import smart_str
from django.utils.translation import gettext as _

from ctags import settings
from ctags.utils import LOGARITHMIC
from ctags.utils import calculate_cloud
from ctags.utils import get_queryset_and_model
from ctags.utils import get_tag_list


qn = connection.ops.quote_name


############
# Managers #
############

class TagManager(models.Manager):

    def update_tags(self, obj, tag_ids):
        """
        Replace the given object's ctags with ctags of the given IDs.
        """
        ctype = ContentType.objects.get_for_model(obj)
        current_tags = list(self.filter(items__content_type__pk=ctype.pk,
                                        items__object_id=obj.pk))

        # Remove ctags which no longer apply
        tags_for_removal = [ctag for ctag in current_tags
                            if ctag.id not in tag_ids]
        if len(tags_for_removal):
            CTaggedItem._default_manager.filter(
                content_type__pk=ctype.pk,
                object_id=obj.pk,
                tag__in=tags_for_removal).delete()
        # Add new ctags, using id (not pk) for speed.
        # https://stackoverflow.com/questions/2165865/x/53100893#53100893
        current_tag_ids = [ctag.id for ctag in current_tags]
        for tag_id in tag_ids:
            if tag_id not in current_tag_ids:
                ctag, created = self.get_or_create(id=tag_id)
                CTaggedItem._default_manager.get_or_create(
                    content_type_id=ctype.pk,
                    object_id=obj.pk,
                    ctag=ctag,
                )

    def add_tag(self, obj, name_en):
        """
        Associates the given object with a ctag.
        """
        try:
            ctag = self.get(name_en=name_en)
        except CTag.DoesNotExist:
            return
        ctype = ContentType.objects.get_for_model(obj)
        CTaggedItem._default_manager.get_or_create(
            ctag=ctag, content_type=ctype, object_id=obj.pk)

    def get_for_object(self, obj):
        """
        Create a queryset matching all ctags associated with the given
        object.
        """
        ctype = ContentType.objects.get_for_model(obj)
        return self.filter(items__content_type__pk=ctype.pk,
                           items__object_id=obj.pk)

    def _get_usage(self, model, counts=False, min_count=None,
                   extra_joins=None, extra_criteria=None, params=None):
        """
        Perform the custom SQL query for ``usage_for_model`` and
        ``usage_for_queryset``.
        """
        if min_count is not None:
            counts = True

        model_table = qn(model._meta.db_table)
        model_pk = '%s.%s' % (model_table, qn(model._meta.pk.column))
        query = """
        SELECT DISTINCT %(ctag)s.id%(count_sql)s
        FROM
            %(ctag)s
            INNER JOIN %(tagged_item)s
                ON %(ctag)s.id = %(tagged_item)s.tag_id
            INNER JOIN %(model)s
                ON %(tagged_item)s.object_id = %(model_pk)s
            %%s
        WHERE %(tagged_item)s.content_type_id = %(content_type_id)s
            %%s
        GROUP BY %(ctag)s.id
        %%s""" % {
            'ctag': qn(self.model._meta.db_table),
            'count_sql': counts and (', COUNT(%s)' % model_pk) or '',
            'tagged_item': qn(CTaggedItem._meta.db_table),
            'model': model_table,
            'model_pk': model_pk,
            'content_type_id': ContentType.objects.get_for_model(model).pk,
        }

        min_count_sql = ''
        if min_count is not None:
            min_count_sql = 'HAVING COUNT(%s) >= %%s' % model_pk
            params.append(min_count)

        cursor = connection.cursor()
        cursor.execute(query % (extra_joins, extra_criteria, min_count_sql),
                       params)
        ctags = []
        for row in cursor.fetchall():
            t = self.model(*row[:2])
            if counts:
                t.count = row[2]
            ctags.append(t)
        return ctags

    def usage_for_model(self, model, counts=False, min_count=None,
                        filters=None):
        """
        Obtain a list of ctags associated with instances of the given
        Model class.

        If ``counts`` is True, a ``count`` attribute will be added to
        each ctag, indicating how many times it has been used against
        the Model class in question.

        If ``min_count`` is given, only ctags which have a ``count``
        greater than or equal to ``min_count`` will be returned.
        Passing a value for ``min_count`` implies ``counts=True``.

        To limit the ctags (and counts, if specified) returned to those
        used by a subset of the Model's instances, pass a dictionary
        of field lookups to be applied to the given Model as the
        ``filters`` argument.
        """
        if filters is None:
            filters = {}

        queryset = model._default_manager.filter()
        for k, v in filters.items():
            # Add support for both Django 4 and inferior versions
            queryset.query.add_q(Q((k, v)))
        usage = self.usage_for_queryset(queryset, counts, min_count)

        return usage

    def usage_for_queryset(self, queryset, counts=False, min_count=None):
        """
        Obtain a list of ctags associated with instances of a model
        contained in the given queryset.

        If ``counts`` is True, a ``count`` attribute will be added to
        each ctag, indicating how many times it has been used against
        the Model class in question.

        If ``min_count`` is given, only ctags which have a ``count``
        greater than or equal to ``min_count`` will be returned.
        Passing a value for ``min_count`` implies ``counts=True``.
        """
        compiler = queryset.query.get_compiler(using=queryset.db)
        where, params = compiler.compile(queryset.query.where)
        extra_joins = ' '.join(compiler.get_from_clause()[0][1:])

        if where:
            extra_criteria = 'AND %s' % where
        else:
            extra_criteria = ''
        return self._get_usage(queryset.model, counts, min_count,
                               extra_joins, extra_criteria, params)

    def related_for_model(self, ctags, model, counts=False, min_count=None):
        """
        Obtain a list of ctags related to a given list of ctags - that
        is, other ctags used by items which have all the given ctags.

        If ``counts`` is True, a ``count`` attribute will be added to
        each ctag, indicating the number of items which have it in
        addition to the given list of ctags.

        If ``min_count`` is given, only ctags which have a ``count``
        greater than or equal to ``min_count`` will be returned.
        Passing a value for ``min_count`` implies ``counts=True``.
        """
        if min_count is not None:
            counts = True

        ctags = get_tag_list(ctags)
        tag_count = len(ctags)
        tagged_item_table = qn(CTaggedItem._meta.db_table)
        query = """
        SELECT %(ctag)s.id, %(ctag)s.name%(count_sql)s
        FROM %(tagged_item)s INNER JOIN %(ctag)s ON
             %(tagged_item)s.tag_id = %(ctag)s.id
        WHERE %(tagged_item)s.content_type_id = %(content_type_id)s
          AND %(tagged_item)s.object_id IN
          (
              SELECT %(tagged_item)s.object_id
              FROM %(tagged_item)s, %(ctag)s
              WHERE %(tagged_item)s.content_type_id = %(content_type_id)s
                AND %(ctag)s.id = %(tagged_item)s.tag_id
                AND %(ctag)s.id IN (%(tag_id_placeholders)s)
              GROUP BY %(tagged_item)s.object_id
              HAVING COUNT(%(tagged_item)s.object_id) = %(tag_count)s
          )
          AND %(ctag)s.id NOT IN (%(tag_id_placeholders)s)
        GROUP BY %(ctag)s.id, %(ctag)s.name
        %(min_count_sql)s
        ORDER BY %(ctag)s.name ASC""" % {
            'ctag': qn(self.model._meta.db_table),
            'count_sql': counts and ', COUNT(%s.object_id)' %
                tagged_item_table or '',
            'tagged_item': tagged_item_table,
            'content_type_id': ContentType.objects.get_for_model(model).pk,
            'tag_id_placeholders': ','.join(['%s'] * tag_count),
            'tag_count': tag_count,
            'min_count_sql': min_count is not None and (
                'HAVING COUNT(%s.object_id) >= %%s' % tagged_item_table) or '',
        }

        params = [ctag.pk for ctag in ctags] * 2
        if min_count is not None:
            params.append(min_count)

        cursor = connection.cursor()
        cursor.execute(query, params)
        related = []
        for row in cursor.fetchall():
            ctag = self.model(*row[:2])
            if counts is True:
                ctag.count = row[2]
            related.append(ctag)
        return related

    def cloud_for_model(self, model, steps=4, distribution=LOGARITHMIC,
                        filters=None, min_count=None):
        """
        Obtain a list of ctags associated with instances of the given
        Model, giving each ctag a ``count`` attribute indicating how
        many times it has been used and a ``font_size`` attribute for
        use in displaying a ctag cloud.

        ``steps`` defines the range of font sizes - ``font_size`` will
        be an integer between 1 and ``steps`` (inclusive).

        ``distribution`` defines the type of font size distribution
        algorithm which will be used - logarithmic or linear. It must
        be either ``ctags.utils.LOGARITHMIC`` or ``ctags.utils.LINEAR``.

        To limit the ctags displayed in the cloud to those associated
        with a subset of the Model's instances, pass a dictionary of
        field lookups to be applied to the given Model as the
        ``filters`` argument.

        To limit the ctags displayed in the cloud to those with a
        ``count`` greater than or equal to ``min_count``, pass a value
        for the ``min_count`` argument.
        """
        ctags = list(self.usage_for_model(model, counts=True, filters=filters,
                                         min_count=min_count))
        return calculate_cloud(ctags, steps, distribution)


class TaggedItemManager(models.Manager):
    """
    FIXME There's currently no way to get the ``GROUP BY`` and ``HAVING``
          SQL clauses required by many of this manager's methods into
          Django's ORM.

          For now, we manually execute a query to retrieve the PKs of
          objects we're interested in, then use the ORM's ``__in``
          lookup to return a ``QuerySet``.

          Now that the queryset-refactor branch is in the trunk, this can be
          tidied up significantly.
    """

    def get_by_model(self, queryset_or_model, ctags):
        """
        Create a ``QuerySet`` containing instances of the specified
        model associated with a given ctag or list of ctags.
        """
        ctags = get_tag_list(ctags)
        tag_count = len(ctags)
        if tag_count == 0:
            # No existing ctags were given
            queryset, model = get_queryset_and_model(queryset_or_model)
            return model._default_manager.none()
        elif tag_count == 1:
            # Optimisation for single ctag - fall through to the simpler
            # query below.
            ctag = ctags[0]
        else:
            return self.get_intersection_by_model(queryset_or_model, ctags)

        queryset, model = get_queryset_and_model(queryset_or_model)
        content_type = ContentType.objects.get_for_model(model)
        opts = self.model._meta
        tagged_item_table = qn(opts.db_table)
        return queryset.extra(
            tables=[opts.db_table],
            where=[
                '%s.content_type_id = %%s' % tagged_item_table,
                '%s.tag_id = %%s' % tagged_item_table,
                '%s.%s = %s.object_id' % (qn(model._meta.db_table),
                                          qn(model._meta.pk.column),
                                          tagged_item_table)
            ],
            params=[content_type.pk, ctag.pk],
        )

    def get_intersection_by_model(self, queryset_or_model, ctags):
        """
        Create a ``QuerySet`` containing instances of the specified
        model associated with *all* of the given list of ctags.
        """
        ctags = get_tag_list(ctags)
        tag_count = len(ctags)
        queryset, model = get_queryset_and_model(queryset_or_model)

        if not tag_count:
            return model._default_manager.none()

        model_table = qn(model._meta.db_table)
        # This query selects the ids of all objects which have all the
        # given ctags.
        query = """
        SELECT %(model_pk)s
        FROM %(model)s, %(tagged_item)s
        WHERE %(tagged_item)s.content_type_id = %(content_type_id)s
          AND %(tagged_item)s.tag_id IN (%(tag_id_placeholders)s)
          AND %(model_pk)s = %(tagged_item)s.object_id
        GROUP BY %(model_pk)s
        HAVING COUNT(%(model_pk)s) = %(tag_count)s""" % {
            'model_pk': '%s.%s' % (model_table, qn(model._meta.pk.column)),
            'model': model_table,
            'tagged_item': qn(self.model._meta.db_table),
            'content_type_id': ContentType.objects.get_for_model(model).pk,
            'tag_id_placeholders': ','.join(['%s'] * tag_count),
            'tag_count': tag_count,
        }

        cursor = connection.cursor()
        cursor.execute(query, [ctag.pk for ctag in ctags])
        object_ids = [row[0] for row in cursor.fetchall()]
        if len(object_ids) > 0:
            return queryset.filter(pk__in=object_ids)
        else:
            return model._default_manager.none()

    def get_union_by_model(self, queryset_or_model, ctags):
        """
        Create a ``QuerySet`` containing instances of the specified
        model associated with *any* of the given list of ctags.
        """
        ctags = get_tag_list(ctags)
        tag_count = len(ctags)
        queryset, model = get_queryset_and_model(queryset_or_model)

        if not tag_count:
            return model._default_manager.none()

        model_table = qn(model._meta.db_table)
        # This query selects the ids of all objects which have any of
        # the given ctags.
        query = """
        SELECT %(model_pk)s
        FROM %(model)s, %(tagged_item)s
        WHERE %(tagged_item)s.content_type_id = %(content_type_id)s
          AND %(tagged_item)s.tag_id IN (%(tag_id_placeholders)s)
          AND %(model_pk)s = %(tagged_item)s.object_id
        GROUP BY %(model_pk)s""" % {
            'model_pk': '%s.%s' % (model_table, qn(model._meta.pk.column)),
            'model': model_table,
            'tagged_item': qn(self.model._meta.db_table),
            'content_type_id': ContentType.objects.get_for_model(model).pk,
            'tag_id_placeholders': ','.join(['%s'] * tag_count),
        }

        cursor = connection.cursor()
        cursor.execute(query, [ctag.pk for ctag in ctags])
        object_ids = [row[0] for row in cursor.fetchall()]
        if len(object_ids) > 0:
            return queryset.filter(pk__in=object_ids)
        else:
            return model._default_manager.none()

    def get_related(self, obj, queryset_or_model, num=None):
        """
        Retrieve a list of instances of the specified model which share
        ctags with the model instance ``obj``, ordered by the number of
        shared ctags in descending order.

        If ``num`` is given, a maximum of ``num`` instances will be
        returned.
        """
        queryset, model = get_queryset_and_model(queryset_or_model)
        model_table = qn(model._meta.db_table)
        content_type = ContentType.objects.get_for_model(obj)
        related_content_type = ContentType.objects.get_for_model(model)
        query = """
        SELECT %(model_pk)s, COUNT(related_tagged_item.object_id) AS %(count)s
        FROM %(model)s, %(tagged_item)s, %(ctag)s,
             %(tagged_item)s related_tagged_item
        WHERE %(tagged_item)s.object_id = %%s
          AND %(tagged_item)s.content_type_id = %(content_type_id)s
          AND %(ctag)s.id = %(tagged_item)s.tag_id
          AND related_tagged_item.content_type_id = %(related_content_type_id)s
          AND related_tagged_item.tag_id = %(tagged_item)s.tag_id
          AND %(model_pk)s = related_tagged_item.object_id"""
        if content_type.pk == related_content_type.pk:
            # Exclude the given instance itself if determining related
            # instances for the same model.
            query += """
          AND related_tagged_item.object_id != %(tagged_item)s.object_id"""
        query += """
        GROUP BY %(model_pk)s
        ORDER BY %(count)s DESC
        %(limit_offset)s"""
        tagging_table = qn(self.model._meta.get_field(
            'ctag').remote_field.model._meta.db_table)
        query = query % {
            'model_pk': '%s.%s' % (model_table, qn(model._meta.pk.column)),
            'count': qn('count'),
            'model': model_table,
            'tagged_item': qn(self.model._meta.db_table),
            'ctag': tagging_table,
            'content_type_id': content_type.pk,
            'related_content_type_id': related_content_type.pk,
            # Hardcoding this for now just to get tests working again - this
            # should now be handled by the query object.
            'limit_offset': num is not None and 'LIMIT %s' or '',
        }

        cursor = connection.cursor()
        params = [obj.pk]
        if num is not None:
            params.append(num)
        cursor.execute(query, params)
        object_ids = [row[0] for row in cursor.fetchall()]
        if len(object_ids) > 0:
            # Use in_bulk here instead of an id__in lookup,
            # because id__in would clobber the ordering.
            object_dict = queryset.in_bulk(object_ids)
            return [object_dict[object_id] for object_id in object_ids
                    if object_id in object_dict]
        else:
            return []


##########
# Models #
##########

class CTag(models.Model):
    """
    Embodies a single, distinct concept that can be interpreted as a category
    or shared property.
    """
    name_en = models.CharField(
        max_length=settings.MAX_TAG_LENGTH,
        unique=True, db_index=True)

    name_ja = models.CharField(
        max_length=settings.MAX_TAG_LENGTH,
        unique=True, db_index=True)

    name_es = models.CharField(
        max_length=settings.MAX_TAG_LENGTH,
        unique=True, db_index=True)

    name_pt = models.CharField(
        max_length=settings.MAX_TAG_LENGTH,
        unique=True, db_index=True)

    approved_en = models.BooleanField(default=False)
    approved_ja = models.BooleanField(default=False)
    approved_es = models.BooleanField(default=False)
    approved_pt = models.BooleanField(default=False)

    objects = TagManager()

    class Meta:
        ordering = (Lower('name_en'),)
        verbose_name = _('ctag')
        verbose_name_plural = _('ctags')

    def __str__(self):
        return _(self.name_en)

class CTagAliasEn(models.Model):
    """
    Little more than a pointer and a display name (used for autocompletion).
    """
    target = models.PositiveIntegerField(_('target ctag id'))
    name = models.CharField(max_length=settings.MAX_TAG_LENGTH,
        unique=True, db_index=True)

class CTaggedItem(models.Model):
    """
    Holds the relationship between a ctag and the item being tagged.
    """
    ctag = models.ForeignKey(
        CTag,
        verbose_name=_('ctag'),
        related_name='items',
        on_delete=models.CASCADE)

    content_type = models.ForeignKey(
        ContentType,
        verbose_name=_('content type'),
        on_delete=models.CASCADE)

    object_id = models.PositiveIntegerField(
        _('object id'),
        db_index=True)

    object = GenericForeignKey(
        'content_type', 'object_id')

    objects = TaggedItemManager()

    class Meta:
        # Enforce unique ctag association per object
        unique_together = (('ctag', 'content_type', 'object_id'),)
        verbose_name = _('tagged item')
        verbose_name_plural = _('tagged items')

    def __str__(self):
        return '%s [%s]' % (smart_str(self.object), smart_str(self.ctag))
