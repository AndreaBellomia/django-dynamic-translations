# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

## 0.3.0 - 2026-09-07

- Add a Django REST Framework mixin for detail lookups on translated fields.
- Add an optional django-filter `TranslatableFilterSet` integration.

## 0.2.0 - 2026-08-19

- Allow `prefetch_translations()` to include translations from selected related models.
- Declare translated manager methods explicitly for better static-analysis support.
- Add an optional Django REST Framework `TranslatableModelSerializer` integration.
- Make `TranslatableAdmin` provide its form automatically and validate custom form bases.
- Expand the public documentation and add contribution guidelines.
- License the project under the MIT License.

## 0.1.0 - 2026-08-18

- Generate a model-specific translation table from `TranslatedField` declarations.
- Expose translated fields as natural model attributes with default-language fallback.
- Add translated queryset filtering and constant-query prefetching.
- Enforce a complete default-language translation.
- Add all-languages Django `ModelForm` and admin integrations.
