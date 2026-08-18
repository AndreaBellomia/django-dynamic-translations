from __future__ import annotations

from typing import Any, cast

from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from .forms import TranslatableModelForm, get_translation_form_field_names
from .models import (
    TranslatableModel,
    TranslatableQuerySet,
    get_default_language_code,
    get_language_choices,
    normalize_language_code,
)


class TranslatableAdmin(admin.ModelAdmin):
    """ModelAdmin that renders one fieldset for every configured language."""

    form = TranslatableModelForm

    def __init__(self, model: type[TranslatableModel], admin_site: admin.AdminSite) -> None:
        if not issubclass(model, TranslatableModel):
            raise ImproperlyConfigured("TranslatableAdmin requires a TranslatableModel.")
        super().__init__(model, admin_site)

    def _get_shared_fields(self, request: HttpRequest, obj: Any = None) -> tuple[Any, ...]:
        if self.fields:
            return tuple(self.fields)

        excluded = set(self.get_exclude(request, obj) or ())
        editable_fields = [
            field.name
            for field in self.model._meta.get_fields()
            if getattr(field, "editable", False)
            and not field.auto_created
            and not field.primary_key
            and field.name not in excluded
        ]
        readonly_fields = [
            field
            for field in self.get_readonly_fields(request, obj)
            if field not in editable_fields
        ]
        return (*editable_fields, *readonly_fields)

    def get_fieldsets(self, request: HttpRequest, obj: Any = None) -> list[tuple[Any, dict]]:
        if self.fieldsets:
            fieldsets: list[tuple[Any, dict[str, Any]]] = list(self.fieldsets)
        else:
            shared_fields = self._get_shared_fields(request, obj)
            fieldsets = [(None, {"fields": shared_fields})] if shared_fields else []

        model = cast(type[TranslatableModel], self.model)
        default_language = get_default_language_code()
        for configured_language, language_name in get_language_choices():
            language_code = normalize_language_code(configured_language)
            title = f"{language_name} ({language_code})"
            if language_code == default_language:
                title = _("%(language)s — default") % {"language": title}
            fieldsets.append(
                (
                    title,
                    {"fields": get_translation_form_field_names(model, language_code)},
                )
            )
        return fieldsets

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        queryset = cast(TranslatableQuerySet, super().get_queryset(request))
        return queryset.prefetch_translations()

    def save_related(
        self,
        request: HttpRequest,
        form: TranslatableModelForm,
        formsets: list[Any],
        change: bool,
    ) -> None:
        super().save_related(request, form, formsets, change)
        form.save_translations()
