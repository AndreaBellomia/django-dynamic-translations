from collections import OrderedDict
from typing import Any, cast

from django.core.validators import EMPTY_VALUES

try:
    from django_filters import Filter, FilterSet
    from django_filters.conf import settings
    from django_filters.constants import ALL_FIELDS
    from django_filters.utils import get_all_model_fields, get_model_field
except ImportError as error:  # pragma: no cover - exercised only without the optional extra
    raise ImportError(
        "django-filter support requires the optional 'filters' extra. "
        "Install django-dynamic-translations[filters]."
    ) from error


class TranslatableFilterSet(FilterSet):
    """FilterSet that discovers and queries fields stored on translation models."""

    @classmethod
    def get_fields(cls) -> OrderedDict[str, list[str]]:
        filterset_class = cast(Any, cls)
        fields = filterset_class._meta.fields
        if fields is None and filterset_class._meta.exclude is not None:
            fields = ALL_FIELDS
        if fields == ALL_FIELDS:
            model = filterset_class._meta.model
            translated_fields = getattr(model, "_translated_fields", {})
            fields = [*get_all_model_fields(model), *translated_fields]

            exclude = filterset_class._meta.exclude or []
            return OrderedDict(
                (field_name, [settings.DEFAULT_LOOKUP_EXPR])
                for field_name in fields
                if field_name not in exclude
            )

        return cast(OrderedDict[str, list[str]], super().get_fields())

    @classmethod
    def get_filters(cls) -> OrderedDict[str, Filter]:
        filterset_class = cast(Any, cls)
        if not filterset_class._meta.model:
            return cls.declared_filters.copy()

        filters = OrderedDict()
        fields = cls.get_fields()
        undefined = []
        translated_fields = getattr(filterset_class._meta.model, "_translated_fields", {})

        for field_name, lookups in fields.items():
            field = get_model_field(filterset_class._meta.model, field_name)
            is_translated = field_name in translated_fields
            if field is None and is_translated:
                field = filterset_class._meta.model._translation_model._meta.get_field(field_name)
            elif field is None:
                undefined.append(field_name)

            for lookup_expr in lookups:
                filter_name = cls.get_filter_name(field_name, lookup_expr)

                if filter_name in cls.declared_filters:
                    filter_instance = cls.declared_filters[filter_name]
                elif field is not None:
                    filter_instance = cls.filter_for_field(field, field_name, lookup_expr)
                    if filter_instance is None:
                        continue
                else:
                    continue

                if is_translated and filter_instance.method is None:
                    cast(Any, filter_instance)._translated_field = True
                filters[filter_name] = filter_instance

        if isinstance(filterset_class._meta.fields, (list, tuple)):
            undefined = [name for name in undefined if name not in cls.declared_filters]

        if undefined:
            raise TypeError(
                "'Meta.fields' must not contain non-model field names: " + ", ".join(undefined)
            )

        filters.update(cls.declared_filters)
        for filter_instance in filters.values():
            if filter_instance.field_name in translated_fields and filter_instance.method is None:
                cast(Any, filter_instance)._translated_field = True
        return filters

    def filter_queryset(self, queryset: Any) -> Any:
        for name, value in self.form.cleaned_data.items():
            filter_instance = self.filters[name]
            if not getattr(filter_instance, "_translated_field", False):
                queryset = filter_instance.filter(queryset, value)
                continue

            if value in EMPTY_VALUES:
                continue
            if filter_instance.distinct:
                queryset = queryset.distinct()

            lookup = f"{filter_instance.field_name}__{filter_instance.lookup_expr}"
            if filter_instance.exclude:
                matching = queryset.translated(**{lookup: value}).values("pk")
                queryset = queryset.exclude(pk__in=matching)
            else:
                queryset = queryset.translated(**{lookup: value})

        return queryset
