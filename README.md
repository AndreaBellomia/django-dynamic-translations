# django-dynamic-translations

Model-specific translations for Django without a shared generic translation table.
The package generates a `<Model>Translation` model from each `TranslatedField`, exposes
the translated values as natural model attributes, and integrates all configured
languages into a single Django form or admin page.

> The project is currently in alpha. Its public API is usable, but may still evolve
> before version 1.0.

## Installation

Install the package:

```bash
pip install django-dynamic-translations
```

Then add it to `INSTALLED_APPS` and configure only the languages supported by the
application:

```python
INSTALLED_APPS = [
    # ...
    "django_dynamic_translations",
]

LANGUAGE_CODE = "en-us"
LANGUAGES = [
    ("en-us", "English (United States)"),
    ("it", "Italiano"),
]
```

Only put application-supported languages in `LANGUAGES`: each language becomes a
section in the generated form.

## Model

```python
from django.db import models
from django_dynamic_translations.models import TranslatableModel, TranslatedField


class Trip(TranslatableModel):
    name = TranslatedField[str](models.CharField(max_length=255))
    slug = TranslatedField[str](models.SlugField(max_length=255))
    description = TranslatedField[str](models.TextField())
```

Run `makemigrations` normally. Django creates both `Trip` and `TripTranslation`.
The default-language translation is required. Other languages fall back to it when
read through `trip.name`, `trip.slug`, or the other aliases.

Use `prefetch_translations()` for lists and paginated querysets:

```python
trips = Trip.objects.order_by("pk").prefetch_translations()
```

## Forms and admin

```python
from django.contrib import admin
from django_dynamic_translations.admin import TranslatableAdmin
from django_dynamic_translations.forms import TranslatableModelForm

from .models import Trip


class TripForm(TranslatableModelForm):
    class Meta:
        model = Trip
        fields = ()


@admin.register(Trip)
class TripAdmin(TranslatableAdmin):
    form = TripForm
    list_display = ("name", "slug")
    search_fields = ("translations__name", "translations__slug")
```

For generated forms without a custom subclass, use
`translatable_modelform_factory(Trip)`.

The form displays all translated fields for all configured languages. The default
language is mandatory. An optional language is saved only when it is complete;
clearing every field removes that translation.

## Development

The project uses `uv`:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

## Releases

GitHub releases publish the matching wheel and source distribution to PyPI through
Trusted Publishing. The Git tag must match the package version, for example `v0.1.0`.
