from __future__ import annotations

import sys
from collections.abc import Iterable
from contextlib import AbstractContextManager
from functools import cache
from typing import Any, ClassVar, cast, overload

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, ValidationError
from django.core.signals import setting_changed
from django.db import models, router, transaction
from django.db.models.base import ModelBase
from django.db.models.query import QuerySet
from django.dispatch import receiver
from django.utils.translation import get_language


@cache
def get_language_choices() -> tuple[tuple[str, str], ...]:
    choices: list[tuple[str, str]] = []
    seen_languages: set[str] = set()
    for configured_code, language_name in settings.LANGUAGES:
        language_code = _normalize_language_code(configured_code)
        if not language_code:
            raise ImproperlyConfigured("LANGUAGES cannot contain an empty language code.")
        if language_code in seen_languages:
            raise ImproperlyConfigured(
                f"LANGUAGES contains the duplicate language code {language_code!r}."
            )
        choices.append((language_code, language_name))
        seen_languages.add(language_code)

    default_language = _normalize_language_code(settings.LANGUAGE_CODE)
    if not default_language:
        raise ImproperlyConfigured("LANGUAGE_CODE must not be empty.")
    if default_language not in seen_languages:
        choices.append((default_language, default_language))
    return tuple(choices)


@cache
def get_supported_language_codes() -> frozenset[str]:
    return frozenset(code.lower().replace("_", "-") for code, _name in get_language_choices())


@receiver(setting_changed)
def _clear_language_configuration_cache(*, setting: str, **kwargs: Any) -> None:
    if setting in {"LANGUAGES", "LANGUAGE_CODE"}:
        get_language_choices.cache_clear()
        get_supported_language_codes.cache_clear()


def _normalize_language_code(language_code: str | None) -> str:
    return (language_code or "").lower().replace("_", "-")


def normalize_language_code(language_code: str | None, *, validate: bool = True) -> str:
    normalized = _normalize_language_code(language_code)
    if validate and normalized not in get_supported_language_codes():
        raise ValidationError({"language_code": f"Unsupported language code: {language_code!r}."})
    return normalized


def get_default_language_code() -> str:
    language_code = normalize_language_code(settings.LANGUAGE_CODE)
    if not language_code:
        raise ImproperlyConfigured("LANGUAGE_CODE must not be empty.")
    return language_code


class TranslationDoesNotExist(AttributeError, ObjectDoesNotExist):
    pass


class MissingDefaultTranslation(ValidationError):
    pass


class BaseTranslation(models.Model):
    objects: ClassVar[models.Manager]

    language_code = models.CharField(
        max_length=15,
        choices=get_language_choices,
        db_index=True,
    )

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        self.language_code = normalize_language_code(cast(str, self.language_code))

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.language_code = normalize_language_code(cast(str, self.language_code))
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class TranslatedField[TranslatedValue]:
    """Declare a field stored on the model-specific translation table."""

    def __init__(self, field: models.Field | None = None) -> None:
        if field is None:
            field = models.TextField()
        if not isinstance(field, models.Field):
            raise TypeError("TranslatedField expects a Django model field instance.")
        if field.is_relation or field.primary_key:
            raise TypeError("TranslatedField only supports non-relational, non-primary-key fields.")
        self.field = field
        self.model: type[models.Model] | None = None
        self.name: str | None = None

    def contribute_to_class(self, cls: type[models.Model], name: str, **kwargs: Any) -> None:
        self.model = cls
        self.name = name
        setattr(cls, name, self)

    @overload
    def __get__(
        self,
        instance: None,
        owner: type[TranslatableModel] | None = None,
    ) -> TranslatedField[TranslatedValue]: ...

    @overload
    def __get__(
        self,
        instance: TranslatableModel,
        owner: type[TranslatableModel] | None = None,
    ) -> TranslatedValue: ...

    def __get__(
        self,
        instance: TranslatableModel | None,
        owner: type[TranslatableModel] | None = None,
    ) -> TranslatedField[TranslatedValue] | TranslatedValue:
        if instance is None:
            return self
        translation = instance._get_translation(use_fallback=True)
        return cast(TranslatedValue, getattr(translation, self._field_name))

    def __set__(self, instance: TranslatableModel, value: TranslatedValue) -> None:
        language_code = instance._language_for_assignment()
        translation = instance._get_translation(
            language_code=language_code,
            use_fallback=False,
            auto_create=True,
        )
        setattr(translation, self._field_name, value)
        instance._dirty_translation_languages.add(language_code)

    @property
    def _field_name(self) -> str:
        if self.name is None:
            raise ImproperlyConfigured("TranslatedField has not been attached to a model.")
        return self.name

    def __repr__(self) -> str:
        return f"<{type(self).__name__} for {self.name or 'unbound'}>"


class TranslatableQuerySet(QuerySet):
    def _get_translatable_model(self) -> type[TranslatableModel]:
        if self.model is None:
            raise ImproperlyConfigured("TranslatableQuerySet is not bound to a model.")
        return cast(type[TranslatableModel], self.model)

    def translated(self, *language_codes: str, **translated_fields: Any) -> TranslatableQuerySet:
        model = self._get_translatable_model()
        requested_fields = {lookup.split("__", 1)[0] for lookup in translated_fields}
        unknown_fields = requested_fields - set(model._translated_fields)
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown translated field(s) for {model.__name__}: {fields}.")

        if language_codes:
            languages = list(
                dict.fromkeys(normalize_language_code(code) for code in language_codes)
            )
        else:
            languages = [model._effective_language_code()]

        lookups = {
            f"translations__{field_lookup}": value
            for field_lookup, value in translated_fields.items()
        }
        queryset = self.filter(
            translations__language_code__in=languages,
            **lookups,
        )
        return queryset if len(languages) == 1 else queryset.distinct()

    def prefetch_translations(self, *related_lookups: str) -> TranslatableQuerySet:
        """Prefetch this model's translations and selected related models' translations."""
        if any(not lookup for lookup in related_lookups):
            raise ValueError("Translation relation paths cannot be empty.")

        translation_lookups = dict.fromkeys(
            ("translations", *(f"{lookup}__translations" for lookup in related_lookups))
        )
        return self.prefetch_related(*translation_lookups)

    def bulk_create(
        self,
        objs: Iterable[models.Model],
        batch_size: Any = None,
        ignore_conflicts: Any = False,
        update_conflicts: Any = False,
        update_fields: Any = None,
        unique_fields: Any = None,
    ) -> list[models.Model]:
        raise NotImplementedError(
            "bulk_create() is unavailable for translatable models because it would bypass "
            "the required default translation."
        )


class TranslatableManager(models.Manager):
    _queryset_class = TranslatableQuerySet

    def get_queryset(self) -> TranslatableQuerySet:
        return cast(TranslatableQuerySet, super().get_queryset())

    def translated(
        self,
        *language_codes: str,
        **translated_fields: Any,
    ) -> TranslatableQuerySet:
        return self.get_queryset().translated(*language_codes, **translated_fields)

    def prefetch_translations(self, *related_lookups: str) -> TranslatableQuerySet:
        return self.get_queryset().prefetch_translations(*related_lookups)


class TranslatableModelBase(ModelBase):
    def __new__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        attrs: dict[str, Any],
        **kwargs: Any,
    ) -> type[models.Model]:
        declared_fields = {
            field_name: value
            for field_name, value in attrs.items()
            if isinstance(value, TranslatedField)
        }
        model = super().__new__(cls, name, bases, attrs, **kwargs)

        inherited_fields: dict[str, TranslatedField] = {}
        for base in reversed(model.__mro__[1:]):
            inherited_fields.update(getattr(base, "_translated_fields", {}))
        inherited_fields.update(declared_fields)
        model._translated_fields = inherited_fields

        if not model._meta.abstract:
            if not inherited_fields:
                raise ImproperlyConfigured(
                    f"Concrete translatable model {model.__name__} has no TranslatedField fields."
                )
            _create_translation_model(model)

        return model


def _create_translation_model(shared_model: type[TranslatableModel]) -> type[BaseTranslation]:
    model_meta = cast(Any, shared_model)._meta
    translation_model_name = f"{shared_model.__name__}Translation"
    master_field_name = cast(str, model_meta.model_name)
    constraint_name = f"{model_meta.app_label}_{model_meta.model_name}_translation_language_unique"

    class Meta:
        app_label = model_meta.app_label
        constraints = [
            models.UniqueConstraint(
                fields=(master_field_name, "language_code"),
                name=constraint_name,
            )
        ]
        ordering = (master_field_name, "language_code")
        verbose_name = f"{model_meta.verbose_name} translation"
        verbose_name_plural = f"{model_meta.verbose_name_plural} translations"

    translation_attrs: dict[str, Any] = {
        "__module__": shared_model.__module__,
        "Meta": Meta,
        "_translation_master_field_name": master_field_name,
        master_field_name: models.ForeignKey(
            shared_model,
            on_delete=models.CASCADE,
            related_name="translations",
        ),
    }
    for field_name, translated_field in shared_model._translated_fields.items():
        translation_attrs[field_name] = translated_field.field.clone()

    translation_model = cast(
        type[BaseTranslation],
        ModelBase(
            translation_model_name,
            (BaseTranslation,),
            translation_attrs,
        ),
    )
    shared_model._translation_model = translation_model
    shared_model._translation_master_field_name = master_field_name
    setattr(sys.modules[shared_model.__module__], translation_model_name, translation_model)
    return translation_model


class TranslatableModel(models.Model, metaclass=TranslatableModelBase):
    objects: ClassVar[TranslatableManager] = TranslatableManager()

    _translated_fields: dict[str, TranslatedField]
    _translation_model: type[BaseTranslation]
    _translation_master_field_name: str

    class Meta:
        abstract = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        translated_values = {
            field_name: kwargs.pop(field_name)
            for field_name in self._translated_fields
            if field_name in kwargs
        }
        super().__init__(*args, **kwargs)
        self._translation_cache: dict[str, BaseTranslation] = {}
        self._loaded_translation_languages: set[str] = set()
        self._dirty_translation_languages: set[str] = set()
        self._all_translations_prefetched = False
        self._prefetch_cache_consumed = False
        self._current_language: str | None = None
        if translated_values:
            self.set_translation(get_default_language_code(), **translated_values)

    @classmethod
    def get_translated_field_names(cls) -> tuple[str, ...]:
        return tuple(cls._translated_fields)

    @classmethod
    def _effective_language_code(cls) -> str:
        active_language = normalize_language_code(get_language(), validate=False)
        if active_language in get_supported_language_codes():
            return active_language
        return get_default_language_code()

    @property
    def language_code(self) -> str:
        return self._current_language or self._effective_language_code()

    def set_current_language(self, language_code: str | None) -> None:
        self._current_language = (
            normalize_language_code(language_code) if language_code is not None else None
        )

    def _language_for_assignment(self) -> str:
        if self._current_language is not None:
            return self._current_language
        if self._state.adding:
            return get_default_language_code()
        return self._effective_language_code()

    def _consume_prefetched_translations(self) -> bool:
        if self._prefetch_cache_consumed:
            return self._all_translations_prefetched

        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("translations")
        if prefetched is None:
            return False

        for translated_object in prefetched:
            language_code = cast(str, translated_object.language_code)
            self._translation_cache[language_code] = translated_object
            self._loaded_translation_languages.add(language_code)
        self._all_translations_prefetched = True
        self._prefetch_cache_consumed = True
        return True

    def _load_translations(self, language_codes: Iterable[str]) -> None:
        requested = set(language_codes)
        if self._consume_prefetched_translations():
            self._loaded_translation_languages.update(requested)
        missing = requested - self._loaded_translation_languages
        if not missing or self._state.adding or self.pk is None:
            self._loaded_translation_languages.update(missing)
            return

        master_lookup = {self._translation_master_field_name: self}
        translations = self._translation_model.objects.filter(
            language_code__in=missing,
            **master_lookup,
        )
        for translated_object in translations:
            self._translation_cache[translated_object.language_code] = translated_object
        self._loaded_translation_languages.update(missing)

    def _get_translation(
        self,
        language_code: str | None = None,
        *,
        use_fallback: bool,
        auto_create: bool = False,
    ) -> BaseTranslation:
        requested_language = normalize_language_code(language_code or self.language_code)
        default_language = get_default_language_code()
        candidates = [requested_language]
        if use_fallback and requested_language != default_language:
            candidates.append(default_language)

        self._load_translations(candidates)
        for candidate in candidates:
            if candidate in self._translation_cache:
                return self._translation_cache[candidate]

        if auto_create:
            master_values = {self._translation_master_field_name: self}
            translated_object = self._translation_model(
                language_code=requested_language,
                **master_values,
            )
            self._translation_cache[requested_language] = translated_object
            self._loaded_translation_languages.add(requested_language)
            return translated_object

        raise TranslationDoesNotExist(
            f"{type(self).__name__} has no translation for {requested_language!r}"
            + (f" or fallback {default_language!r}." if use_fallback else ".")
        )

    def get_translation(
        self,
        language_code: str | None = None,
        *,
        use_fallback: bool = False,
    ) -> BaseTranslation:
        return self._get_translation(
            language_code=language_code,
            use_fallback=use_fallback,
        )

    def get_translations(self, *language_codes: str) -> dict[str, BaseTranslation]:
        """Return available translations with at most one database query."""
        normalized_languages = tuple(
            dict.fromkeys(
                normalize_language_code(language_code)
                for language_code in (language_codes or get_supported_language_codes())
            )
        )
        self._load_translations(normalized_languages)
        return {
            language_code: self._translation_cache[language_code]
            for language_code in normalized_languages
            if language_code in self._translation_cache
        }

    def set_translation(self, language_code: str, **translated_values: Any) -> BaseTranslation:
        unknown_fields = set(translated_values) - set(self._translated_fields)
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown translated field(s) for {type(self).__name__}: {fields}.")

        normalized_language = normalize_language_code(language_code)
        translated_object = self._get_translation(
            language_code=normalized_language,
            use_fallback=False,
            auto_create=True,
        )
        for field_name, value in translated_values.items():
            setattr(translated_object, field_name, value)
        self._dirty_translation_languages.add(normalized_language)
        return translated_object

    def clear_translation_cache(self) -> None:
        dirty_translations = {
            language_code: self._translation_cache[language_code]
            for language_code in self._dirty_translation_languages
            if language_code in self._translation_cache
        }
        self._translation_cache = dirty_translations
        self._loaded_translation_languages = set(dirty_translations)
        self._all_translations_prefetched = False
        self._prefetch_cache_consumed = False
        getattr(self, "_prefetched_objects_cache", {}).pop("translations", None)

    def _validate_translation(self, translated_object: BaseTranslation) -> None:
        exclude = None
        if self._state.adding:
            exclude = {self._translation_master_field_name}
        translated_object.full_clean(
            exclude=exclude,
            validate_unique=False,
            validate_constraints=False,
        )

    def _get_required_default_translation(self) -> BaseTranslation:
        default_language = get_default_language_code()
        try:
            translated_object = self._get_translation(
                language_code=default_language,
                use_fallback=False,
            )
            self._validate_translation(translated_object)
        except (TranslationDoesNotExist, ValidationError) as error:
            raise MissingDefaultTranslation(
                f"{type(self).__name__} requires a complete {default_language!r} translation."
            ) from error
        return translated_object

    def save(self, *args: Any, **kwargs: Any) -> None:
        translated_update_fields: set[str] = set()
        skip_shared_save = False
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return
            translated_update_fields = update_fields & set(self._translated_fields)
            shared_update_fields = update_fields - translated_update_fields
            if not shared_update_fields and not self._state.adding:
                skip_shared_save = True
                kwargs.pop("update_fields")
            else:
                kwargs["update_fields"] = shared_update_fields

        default_translation = self._get_required_default_translation()
        dirty_translations = [
            self._translation_cache[language_code]
            for language_code in self._dirty_translation_languages
            if language_code in self._translation_cache
        ]
        if default_translation._state.adding and default_translation not in dirty_translations:
            dirty_translations.append(default_translation)
        for translated_object in dirty_translations:
            self._validate_translation(translated_object)

        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        atomic_context = cast(
            AbstractContextManager[None],
            transaction.atomic(using=using),
        )
        with atomic_context:
            if not skip_shared_save:
                super().save(*args, **kwargs)
            for translated_object in dirty_translations:
                setattr(translated_object, self._translation_master_field_name, self)
                translation_save_kwargs: dict[str, Any] = {"using": using}
                if translated_update_fields and not translated_object._state.adding:
                    translation_save_kwargs["update_fields"] = translated_update_fields
                translated_object.save(**translation_save_kwargs)
                self._dirty_translation_languages.discard(translated_object.language_code)

    def refresh_from_db(self, *args: Any, **kwargs: Any) -> None:
        super().refresh_from_db(*args, **kwargs)
        self._translation_cache = {}
        self._loaded_translation_languages = set()
        self._dirty_translation_languages = set()
        self._all_translations_prefetched = False
        self._prefetch_cache_consumed = False
        getattr(self, "_prefetched_objects_cache", {}).pop("translations", None)
