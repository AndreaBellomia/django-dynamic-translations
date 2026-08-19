from typing import Any, cast

try:
    from rest_framework import serializers
    from rest_framework.utils.field_mapping import get_nested_relation_kwargs
    from rest_framework.validators import UniqueValidator
except ImportError as error:  # pragma: no cover - exercised only without the optional extra
    raise ImportError(
        "Django REST Framework support requires the optional 'drf' extra. "
        "Install django-dynamic-translations[drf]."
    ) from error


class _TranslatedUniqueValidator(UniqueValidator):
    def __init__(self, *args: Any, master_field_name: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.master_field_name = master_field_name

    def exclude_current_instance(self, queryset: Any, instance: Any) -> Any:
        if instance is None:
            return queryset
        return queryset.exclude(
            **{
                self.master_field_name: instance,
                "language_code": instance.language_code,
            }
        )


class TranslatableModelSerializer(serializers.ModelSerializer):
    """ModelSerializer that discovers and builds fields stored on translation models."""

    def get_default_field_names(
        self,
        declared_fields: dict[str, serializers.Field],
        model_info: Any,
    ) -> list[str]:
        field_names = super().get_default_field_names(declared_fields, model_info)
        model = cast(Any, self).Meta.model
        translated_fields = getattr(model, "_translated_fields", {})
        field_names.extend(name for name in translated_fields if name not in field_names)
        return field_names

    def build_field(
        self,
        field_name: str,
        info: Any,
        model_class: type[Any],
        nested_depth: int,
    ) -> tuple[type[serializers.Field], dict[str, Any]]:
        translated_fields = getattr(model_class, "_translated_fields", {})
        if field_name in translated_fields:
            translation_model = model_class._translation_model
            model_field = translation_model._meta.get_field(field_name)
            field_class, field_kwargs = self.build_standard_field(field_name, model_field)
            field_kwargs["validators"] = [
                _TranslatedUniqueValidator(
                    queryset=validator.queryset,
                    message=validator.message,
                    lookup=validator.lookup,
                    master_field_name=model_class._translation_master_field_name,
                )
                if type(validator) is UniqueValidator
                else validator
                for validator in field_kwargs.get("validators", ())
            ]
            return field_class, field_kwargs
        return super().build_field(field_name, info, model_class, nested_depth)

    def build_nested_field(
        self,
        field_name: str,
        relation_info: Any,
        nested_depth: int,
    ) -> tuple[type[serializers.BaseSerializer], dict[str, Any]]:
        class NestedSerializer(TranslatableModelSerializer):
            class Meta:
                model = relation_info.related_model
                depth = nested_depth - 1
                fields = "__all__"

        return NestedSerializer, get_nested_relation_kwargs(relation_info)
