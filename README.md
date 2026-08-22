# django-dynamic-translations

[![PyPI](https://img.shields.io/pypi/v/django-dynamic-translations.svg)](https://pypi.org/project/django-dynamic-translations/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-dynamic-translations.svg)](https://pypi.org/project/django-dynamic-translations/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/AndreaBellomia/django-dynamic-translations/blob/main/LICENSE)

Natural, model-specific translations for Django.

`django-dynamic-translations` lets you declare translated values directly on a Django
model while storing them in a generated, model-specific translation table. Application
code reads familiar attributes such as `article.title`; the library handles active
languages, fallback, forms, admin integration, query helpers, and optional Django REST
Framework serializers.

```python
class Article(TranslatableModel):
    title = TranslatedField[str](models.CharField(max_length=200))
    slug = TranslatedField[str](models.SlugField(max_length=200, unique=True))
    body = TranslatedField[str](models.TextField())
    is_published = models.BooleanField(default=False)
```

The declaration above generates an `ArticleTranslation` model and exposes `title`,
`slug`, and `body` as language-aware attributes on `Article`.

> [!IMPORTANT]
> The project is currently alpha software. Its public API is usable and tested, but it
> may evolve before version 1.0.

## Highlights

- One concrete translation table per translatable model; no generic foreign keys.
- Natural attribute access through `article.title`, `article.slug`, and similar aliases.
- Automatic fallback to the configured default language.
- A required, complete default translation for every saved object.
- Query helpers for translated filtering and constant-query prefetching.
- Automatic all-languages Django Admin forms.
- Reusable `ModelForm` integration for standalone workflows.
- Optional Django REST Framework serializer support.
- Normal Django migrations, relations, field validation, and database constraints.
- Typed public APIs for Python 3.12 and newer.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [How storage works](#how-storage-works)
- [Reading and writing translations](#reading-and-writing-translations)
- [Queries and performance](#queries-and-performance)
- [Forms](#forms)
- [Django Admin](#django-admin)
- [Django REST Framework](#django-rest-framework)
- [Validation and lifecycle rules](#validation-and-lifecycle-rules)
- [Static typing](#static-typing)
- [Development and contributing](#development-and-contributing)

## Installation

The package requires Python 3.12+ and Django 5.2–6.1.

```bash
python -m pip install django-dynamic-translations
```

For Django REST Framework support, install the optional extra:

```bash
python -m pip install "django-dynamic-translations[drf]"
```

Add the application to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # Django and project applications...
    "django_dynamic_translations",
]
```

Configure the default language and every language your application supports:

```python
LANGUAGE_CODE = "en-us"

LANGUAGES = [
    ("en-us", "English (United States)"),
    ("it", "Italiano"),
    ("de", "Deutsch"),
]
```

Only add application-supported languages to `LANGUAGES`. Each configured language is
available to the translation API and becomes a section in generated forms.

For request-driven language selection, enable Django's locale middleware after session
middleware:

```python
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    # ...
]
```

## Quick start

### 1. Declare translated fields

Inherit from `TranslatableModel` and wrap each translated Django field with
`TranslatedField`:

```python
from django.db import models

from django_dynamic_translations.models import TranslatableModel, TranslatedField


class Category(TranslatableModel):
    name = TranslatedField[str](models.CharField(max_length=100))
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    def __str__(self) -> str:
        return self.name


class Article(TranslatableModel):
    title = TranslatedField[str](models.CharField(max_length=200))
    slug = TranslatedField[str](models.SlugField(max_length=200, unique=True))
    body = TranslatedField[str](models.TextField())

    is_published = models.BooleanField(default=False)
    categories = models.ManyToManyField(Category, blank=True)

    def __str__(self) -> str:
        return self.title
```

`TranslatedField` accepts ordinary, non-relational Django model fields. Their settings
are preserved on the generated translation model, including `blank`, `max_length`,
validators, widgets, and uniqueness.

### 2. Create migrations

Use Django's normal migration workflow:

```bash
python manage.py makemigrations
python manage.py migrate
```

The migration contains the shared models plus generated `CategoryTranslation` and
`ArticleTranslation` models. Each translation belongs to one object and one normalized
language code.

### 3. Create the default translation

Translated keyword arguments passed while creating an object become its default-language
translation:

```python
article = Article.objects.create(
    title="A practical guide to Django",
    slug="practical-django-guide",
    body="The English article body.",
    is_published=True,
)
```

The default translation is required. Saving a new object without all required default
translated fields raises `MissingDefaultTranslation`.

### 4. Add another language

```python
article.set_translation(
    "it",
    title="Una guida pratica a Django",
    slug="guida-pratica-django",
    body="Il contenuto italiano dell'articolo.",
)
article.save()
```

`set_translation()` changes the in-memory translation. `save()` persists the shared
object and every dirty translation atomically.

### 5. Read using the active language

```python
from django.utils import translation


with translation.override("it"):
    assert article.title == "Una guida pratica a Django"

with translation.override("de"):
    # No German translation exists, so the default English value is returned.
    assert article.title == "A practical guide to Django"
```

In an HTTP request, `LocaleMiddleware` activates the language selected by Django, such
as the language negotiated from `Accept-Language`.

## How storage works

For every concrete `TranslatableModel`, the library generates a concrete translation
model:

```text
Article                         ArticleTranslation
--------------------------      --------------------------------
id                              id
is_published                    article_id  -> Article
categories                      language_code
                                title
                                slug
                                body
```

The generated table has a uniqueness constraint on the parent object and language code.
There can therefore be at most one translation for each object-language pair.

The generated model is registered in the same Django application and module as its
parent. It can be imported when direct access is useful:

```python
from myapp.models import Article, ArticleTranslation
```

Most application code should use the natural aliases and translation methods on
`Article` rather than querying `ArticleTranslation` directly.

## Reading and writing translations

### Select a language for one object

`set_current_language()` overrides the active Django language for a specific instance:

```python
article.set_current_language("it")
print(article.title)

article.set_current_language(None)  # Follow Django's active language again.
```

Assignments use the selected language. Existing objects without an explicit selection
use Django's active language:

```python
article.set_current_language("it")
article.title = "Django: guida pratica"
article.save(update_fields={"title"})
```

New objects always treat translated constructor values as the required default-language
translation.

### Access translation objects directly

```python
italian = article.get_translation("it")
print(italian.title)

available = article.get_translations("en-us", "it", "de")
print(available.keys())  # dict_keys(['en-us', 'it'])
```

`get_translation()` does not fall back unless requested explicitly:

```python
translation_object = article.get_translation("de", use_fallback=True)
```

### Clear the instance cache

Translations are cached per model instance. Clear that cache after out-of-band database
updates when the current instance must reload translation rows:

```python
article.clear_translation_cache()
```

`refresh_from_db()` also resets translation state.

## Queries and performance

### Filter translated values

Use `translated()` rather than manually spelling the generated relation:

```python
article = Article.objects.translated(slug="guida-pratica-django").get()
```

Without an explicit language, the query uses the effective active language:

```python
with translation.override("it"):
    articles = Article.objects.translated(title__icontains="django")
```

Pass one or more language codes when the query must be explicit:

```python
articles = Article.objects.translated("en-us", "it", title__icontains="django")
```

Translated filtering matches stored translations; it does not apply fallback inside the
SQL query.

### Avoid N+1 queries

Use `prefetch_translations()` for lists, pagination, serializers, and templates:

```python
articles = Article.objects.order_by("pk").prefetch_translations()
```

This evaluates as one query for the shared objects and one query for their translations.
Reading any translated alias afterwards does not issue another query.

Pass relation paths to prefetch translations belonging to related translatable models:

```python
articles = Article.objects.prefetch_translations("categories")
```

Nested paths are supported:

```python
articles = Article.objects.prefetch_translations("categories__parent")
```

Each path is expanded to its generated `translations` relation. The related model at the
end of the path must be translatable.

## Forms

### Standalone generated forms

Create a reusable form class with `translatable_modelform_factory()`:

```python
from django_dynamic_translations.forms import translatable_modelform_factory


ArticleForm = translatable_modelform_factory(Article)
```

By default, the form includes every editable shared model field plus translated fields
for every configured language. Restrict only the shared fields when needed:

```python
ArticleForm = translatable_modelform_factory(
    Article,
    fields=("is_published", "categories"),
)
```

Translated fields are always added for every configured language. `exclude=(...)` is
also supported for shared model fields.

### Custom forms

Inherit from `TranslatableModelForm` for custom validation, widgets, or form methods:

```python
from django.core.exceptions import ValidationError

from django_dynamic_translations.forms import TranslatableModelForm


class ArticleForm(TranslatableModelForm):
    class Meta:
        model = Article
        fields = ("is_published", "categories")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_published") and not cleaned_data.get("categories"):
            raise ValidationError("Published articles need at least one category.")
        return cleaned_data
```

The default-language section is mandatory. An optional language is saved only when all
of its required fields are complete. Clearing every field for an optional language
deletes that translation.

`save(commit=False)` follows Django conventions. Call `save_m2m()` after saving the
instance to persist many-to-many values and deferred translation deletions.

## Django Admin

Use `TranslatableAdmin`; no form declaration or factory call is required:

```python
from django.contrib import admin

from django_dynamic_translations.admin import TranslatableAdmin

from .models import Article


@admin.register(Article)
class ArticleAdmin(TranslatableAdmin):
    list_display = ("title", "slug", "is_published")
    search_fields = ("translations__title", "translations__slug")
    list_filter = ("is_published",)
```

The admin automatically:

- generates a form backed by `TranslatableModelForm`;
- creates one fieldset for each configured language;
- identifies the default-language section;
- loads translations efficiently for list views;
- saves shared values and translations together.

When custom form behavior is needed, inherit from `TranslatableModelForm` and assign the
class to the admin. The admin supplies the model and field list, so `Meta` is optional
when the form is used only by that admin:

```python
class ArticleAdminForm(TranslatableModelForm):
    def clean(self):
        cleaned_data = super().clean()
        # Project-specific validation.
        return cleaned_data


@admin.register(Article)
class ArticleAdmin(TranslatableAdmin):
    form = ArticleAdminForm
```

Using a plain `forms.ModelForm` with `TranslatableAdmin` raises an explicit configuration
error instead of silently omitting translations.

## Django REST Framework

Install the optional extra:

```bash
python -m pip install "django-dynamic-translations[drf]"
```

Subclass `TranslatableModelSerializer`. It discovers translated fields from the
generated translation model, including when `fields = "__all__"` is used:

```python
from django_dynamic_translations.rest_framework import TranslatableModelSerializer


class CategorySerializer(TranslatableModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name")


class ArticleSerializer(TranslatableModelSerializer):
    categories = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = Article
        fields = "__all__"
```

Translated serializer fields preserve the generated model field's type, length, blank
rules, and validators. Explicit field lists, `exclude`, and nested serializers created
through `Meta.depth` are supported.

Use `TranslatableLookupMixin` when a detail endpoint's `lookup_field` is translated.
The mixin resolves the value through `translated()` in Django's active language, with
the same default-language fallback used when reading translated aliases:

```python
from django_dynamic_translations.rest_framework import TranslatableLookupMixin


class ArticleViewSet(TranslatableLookupMixin, ModelViewSet):
    queryset = Article.objects.prefetch_translations("categories")
    serializer_class = ArticleSerializer
    lookup_field = "slug"
```

The mixin leaves ordinary, non-translated lookup fields unchanged. Use a prefetched
queryset in list endpoints to avoid per-object translation queries.

With `LocaleMiddleware`, serialized aliases follow the request's active language and
fall back to the default language. Creates write the required default translation;
updates assign translated values to the instance's selected or active language.

For endpoints that accept several languages in one request, model that payload
explicitly and call `set_translation()` for each language rather than relying on the
single-language aliases.

## Validation and lifecycle rules

- A complete default-language translation is required before a new object can be saved.
- Language codes are normalized to lowercase BCP 47-style values such as `en-us`.
- Unsupported language codes are rejected when translations are written directly.
- A translated alias reads the active language first, then the default language.
- Forms require every non-blank field when an optional language contains any content.
- `save(update_fields={...})` accepts translated alias names.
- Shared-object and translation writes run inside a database transaction.
- `bulk_create()` is intentionally unavailable for translatable models because it would
  bypass the required default translation.
- `TranslatedField` supports scalar Django fields, not relations or primary keys.

## Static typing

The package ships a `py.typed` marker and exposes generic `TranslatedField` declarations:

```python
title = TranslatedField[str](models.CharField(max_length=200))
```

Some language servers collapse Django custom managers to `BaseManager`. If the editor
does not see `translated()` or `prefetch_translations()`, narrow the manager without
changing runtime behavior:

```python
from typing import cast

from django_dynamic_translations.models import TranslatableManager


manager = cast(TranslatableManager, Article.objects)
articles = manager.prefetch_translations("categories")
```

## Public API overview

| Module | Main APIs |
| --- | --- |
| `django_dynamic_translations.models` | `TranslatableModel`, `TranslatedField`, `TranslatableManager`, `TranslatableQuerySet` |
| `django_dynamic_translations.forms` | `TranslatableModelForm`, `translatable_modelform_factory`, translation form-field naming helpers |
| `django_dynamic_translations.admin` | `TranslatableAdmin` |
| `django_dynamic_translations.rest_framework` | `TranslatableModelSerializer` when the `drf` extra is installed |

## Development and contributing

The project uses [uv](https://docs.astral.sh/uv/) for dependency and environment
management:

```bash
git clone https://github.com/AndreaBellomia/django-dynamic-translations.git
cd django-dynamic-translations
uv sync
uv run pytest
```

Run the complete local quality gate before opening a pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Bug reports, documentation improvements, tests, and focused feature proposals are
welcome. See the
[contribution guide](https://github.com/AndreaBellomia/django-dynamic-translations/blob/main/CONTRIBUTING.md)
for the development workflow and pull request expectations.

## Releases

GitHub releases publish the matching wheel and source distribution to PyPI through
Trusted Publishing. Release tags must be `v` followed by the exact package version.
Release notes are maintained in the
[changelog](https://github.com/AndreaBellomia/django-dynamic-translations/blob/main/CHANGELOG.md).

## License

`django-dynamic-translations` is available under the
[MIT License](https://github.com/AndreaBellomia/django-dynamic-translations/blob/main/LICENSE).
