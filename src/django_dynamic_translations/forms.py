from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, cast

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models, router, transaction
from django.forms.models import ModelFormMetaclass
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .models import (
    TranslatableModel,
    get_default_language_code,
    get_language_choices,
    normalize_language_code,
)


def get_translation_form_field_name(language_code: str, field_name: str) -> str:
    """Return the stable form field name for one language and translated field."""
    language_key = slugify(normalize_language_code(language_code)).replace("-", "_")
    return f"translation__{language_key}__{field_name}"


def get_translation_form_field_names(
    model: type[TranslatableModel],
    language_code: str,
) -> tuple[str, ...]:
    return tuple(
        get_translation_form_field_name(language_code, field_name)
        for field_name in model.get_translated_field_names()
    )


def _get_translation_model_field(
    model: type[TranslatableModel],
    field_name: str,
) -> models.Field:
    return cast(models.Field, cast(Any, model)._translation_model._meta.get_field(field_name))


def _build_translation_form_fields(
    model: type[TranslatableModel],
) -> dict[str, forms.Field]:
    default_language = get_default_language_code()
    form_fields: dict[str, forms.Field] = {}

    for language_code, _language_name in get_language_choices():
        normalized_language = normalize_language_code(language_code)
        for field_name in model.get_translated_field_names():
            model_field = _get_translation_model_field(model, field_name)
            form_field = model_field.formfield()
            if form_field is None:
                raise ImproperlyConfigured(
                    f"Translated field {model.__name__}.{field_name} cannot be used in a form."
                )
            form_field.required = normalized_language == default_language and not model_field.blank
            cast(Any, form_field.widget).attrs.setdefault("lang", normalized_language)
            form_fields[get_translation_form_field_name(normalized_language, field_name)] = (
                form_field
            )

    return form_fields


class TranslatableModelFormMetaclass(ModelFormMetaclass):
    def __new__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        attrs: dict[str, Any],
    ) -> type[forms.ModelForm]:
        meta = attrs.get("Meta")
        model = getattr(meta, "model", None)
        if isinstance(model, type) and issubclass(model, TranslatableModel):
            for field_name, form_field in _build_translation_form_fields(model).items():
                attrs.setdefault(field_name, form_field)
        return cast(type[forms.ModelForm], super().__new__(cls, name, bases, attrs))


class TranslatableModelForm(forms.ModelForm, metaclass=TranslatableModelFormMetaclass):
    """ModelForm that edits every configured language in a single submission."""

    _translation_values: dict[str, dict[str, Any]]
    _translations_to_delete: set[str]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        supplied_initial = kwargs.get("initial") or {}
        super().__init__(*args, **kwargs)
        if not isinstance(self.instance, TranslatableModel):
            raise ImproperlyConfigured(
                f"{type(self).__name__} must be bound to a TranslatableModel subclass."
            )

        languages = tuple(language_code for language_code, _name in get_language_choices())
        translations = self.instance.get_translations(*languages)
        for language_code, translated_object in translations.items():
            for field_name in self.instance.get_translated_field_names():
                form_field_name = get_translation_form_field_name(language_code, field_name)
                if form_field_name not in supplied_initial:
                    self.initial[form_field_name] = getattr(translated_object, field_name)

        self._translation_values = {}
        self._translations_to_delete = set()

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        model = cast(type[TranslatableModel], cast(Any, self)._meta.model)
        default_language = get_default_language_code()

        for configured_language, _language_name in get_language_choices():
            language_code = normalize_language_code(configured_language)
            values: dict[str, Any] = {}
            has_content = False

            for field_name in model.get_translated_field_names():
                form_field_name = get_translation_form_field_name(language_code, field_name)
                value = cleaned_data.get(form_field_name)
                values[field_name] = value
                if value not in self.fields[form_field_name].empty_values:
                    has_content = True

            should_save = language_code == default_language or has_content
            if not should_save:
                self._translations_to_delete.add(language_code)
                continue

            self._translation_values[language_code] = values
            if language_code == default_language:
                continue

            for field_name, value in values.items():
                model_field = _get_translation_model_field(model, field_name)
                form_field_name = get_translation_form_field_name(language_code, field_name)
                if (
                    not model_field.blank
                    and value in self.fields[form_field_name].empty_values
                    and not self.has_error(form_field_name)
                ):
                    self.add_error(
                        form_field_name,
                        ValidationError(
                            _("Complete every required field for this language."),
                            code="required",
                        ),
                    )

        return cleaned_data

    def _apply_translations(self) -> None:
        existing_translations = self.instance.get_translations(
            *self._translation_values,
        )
        for language_code, values in self._translation_values.items():
            translated_object = existing_translations.get(language_code)
            if translated_object is not None and all(
                getattr(translated_object, field_name) == value
                for field_name, value in values.items()
            ):
                continue
            self.instance.set_translation(language_code, **values)

    def save(self, commit: bool = True) -> TranslatableModel:
        instance = cast(TranslatableModel, super().save(commit=False))
        self._apply_translations()

        if commit:
            using = router.db_for_write(type(instance), instance=instance)
            atomic_context = cast(
                AbstractContextManager[None],
                transaction.atomic(using=using),
            )
            with atomic_context:
                instance.save(using=using)
                self._save_m2m()
        return instance

    cast(Any, save).alters_data = True

    def _save_m2m(self) -> None:
        super()._save_m2m()
        self.save_translations()

    def save_translations(self) -> None:
        """Finish deferred translation deletes after the parent instance is saved."""
        if not self._translations_to_delete or self.instance.pk is None:
            return

        translation_model = cast(Any, self.instance)._translation_model
        master_field_name = cast(Any, self.instance)._translation_master_field_name
        translation_model.objects.filter(
            **{
                master_field_name: self.instance,
                "language_code__in": self._translations_to_delete,
            }
        ).delete()
        self._translations_to_delete.clear()
        self.instance.clear_translation_cache()

    cast(Any, save_translations).alters_data = True


def translatable_modelform_factory(
    model: type[TranslatableModel],
    *,
    form: type[TranslatableModelForm] = TranslatableModelForm,
    fields: str | tuple[str, ...] = "__all__",
    exclude: tuple[str, ...] | None = None,
) -> type[TranslatableModelForm]:
    """Create a reusable all-languages ModelForm for a translatable model."""
    base_meta = getattr(form, "Meta", object)
    meta = type(
        "Meta",
        (base_meta,),
        {
            "model": model,
            "fields": fields,
            "exclude": exclude,
        },
    )
    return cast(
        type[TranslatableModelForm],
        TranslatableModelFormMetaclass(
            f"{model.__name__}TranslationForm",
            (form,),
            {"Meta": meta},
        ),
    )
