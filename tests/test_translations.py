from typing import Any, cast

import pytest
from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import translation

from django_dynamic_translations.admin import TranslatableAdmin
from django_dynamic_translations.forms import (
    TranslatableModelForm,
    get_translation_form_field_name,
    translatable_modelform_factory,
)
from django_dynamic_translations.models import MissingDefaultTranslation
from tests.test_app.forms import ArticleForm
from tests.test_app.models import (
    Article,
    ArticleTranslation,
    Category,
    Place,
    PlaceSection,
)

DEFAULT_TRANSLATION = {
    "title": "Amalfi Coast",
    "slug": "amalfi-coast",
    "body": "A journey along the Amalfi Coast.",
}
ITALIAN_TRANSLATION = {
    "title": "Costiera Amalfitana",
    "slug": "costiera-amalfitana",
    "body": "Un viaggio lungo la Costiera Amalfitana.",
}


class TestGeneratedModel:
    def test_translation_model_contains_every_declared_field(self):
        translation_meta = cast(Any, ArticleTranslation)._meta
        field_names = {field.name for field in translation_meta.fields}

        assert Article.get_translated_field_names() == ("title", "slug", "body")
        assert {"article", "language_code", "title", "slug", "body"} <= field_names


@pytest.mark.django_db
class TestTranslationLifecycle:
    def test_aliases_use_active_language_and_fallback(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()

        article.clear_translation_cache()
        with translation.override("it"):
            assert article.title == ITALIAN_TRANSLATION["title"]

        article.clear_translation_cache()
        with translation.override("de"):
            assert article.title == DEFAULT_TRANSLATION["title"]

    def test_default_translation_is_required(self):
        with pytest.raises(MissingDefaultTranslation, match="complete"):
            Article(title="Incomplete").save()

    def test_unsupported_language_is_rejected(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)

        with pytest.raises(ValidationError, match="Unsupported language code"):
            ArticleTranslation.objects.create(
                article=article,
                language_code="invalid",
                **ITALIAN_TRANSLATION,
            )


@pytest.mark.django_db
class TestTranslationQueries:
    def test_aliases_share_one_lazy_translation_query(self, django_assert_num_queries):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article = Article.objects.get(pk=article.pk)

        with django_assert_num_queries(1):
            assert article.title == DEFAULT_TRANSLATION["title"]
            assert article.slug == DEFAULT_TRANSLATION["slug"]
            assert article.body == DEFAULT_TRANSLATION["body"]

    def test_prefetch_has_constant_query_count(self, django_assert_num_queries):
        for index in range(5):
            Article.objects.create(
                title=f"Article {index}",
                slug=f"article-{index}",
                body=f"Body {index}",
            )

        with django_assert_num_queries(2):
            articles = list(Article.objects.order_by("pk").prefetch_translations())

        with django_assert_num_queries(0):
            assert [article.title for article in articles] == [
                f"Article {index}" for index in range(5)
            ]

    def test_prefetch_can_include_related_models_translations(self, django_assert_num_queries):
        category = Category.objects.create(name="Coast")
        category.set_translation("it", name="Costa")
        category.save()
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()
        article.categories.add(category)

        with django_assert_num_queries(4):
            article = Article.objects.prefetch_translations("categories").get()

        with translation.override("it"), django_assert_num_queries(0):
            assert article.title == ITALIAN_TRANSLATION["title"]
            assert [item.name for item in article.categories.all()] == ["Costa"]

    def test_prefetch_rejects_empty_related_path(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            Article.objects.prefetch_translations("")

    def test_paginated_prefetch_is_constant(self, django_assert_num_queries):
        for index in range(3):
            Article.objects.create(
                title=f"Article {index}",
                slug=f"article-{index}",
                body=f"Body {index}",
            )
        paginator = Paginator(Article.objects.order_by("pk").prefetch_translations(), 2)

        with django_assert_num_queries(3):
            page = paginator.page(1)
            assert [article.title for article in page] == ["Article 0", "Article 1"]

    def test_translated_filter_uses_one_query(self, django_assert_num_queries):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()

        with translation.override("it"), django_assert_num_queries(1):
            result = Article.objects.translated(slug="costiera-amalfitana").get()

        assert result == article


@pytest.mark.django_db
class TestTranslationForm:
    def test_factory_includes_shared_model_fields_by_default(self):
        form_class = translatable_modelform_factory(Article)

        assert "categories" in form_class.base_fields
        assert get_translation_form_field_name("en-us", "title") in form_class.base_fields

    def test_factory_accepts_an_explicit_shared_field_subset(self):
        form_class = translatable_modelform_factory(Article, fields=())

        assert "categories" not in form_class.base_fields
        assert get_translation_form_field_name("en-us", "title") in form_class.base_fields

    def test_form_exposes_every_configured_language(self):
        form = ArticleForm()

        english_title = get_translation_form_field_name("en-us", "title")
        italian_title = get_translation_form_field_name("it", "title")
        assert form.fields[english_title].required is True
        assert form.fields[italian_title].required is False

    def test_form_saves_languages_together(self):
        form = ArticleForm(data=self._form_data())

        assert form.is_valid(), form.errors
        article = form.save()
        assert ArticleTranslation.objects.filter(article=article).count() == 2

    def test_optional_language_must_be_complete(self):
        data = self._form_data(include_italian=False)
        data[get_translation_form_field_name("it", "title")] = ITALIAN_TRANSLATION["title"]
        form = ArticleForm(data=data)

        assert not form.is_valid()
        assert form.has_error(get_translation_form_field_name("it", "slug"))

    def test_clearing_optional_language_deletes_it(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()
        form = ArticleForm(data=self._form_data(include_italian=False), instance=article)

        assert form.is_valid(), form.errors
        form.save()
        assert not ArticleTranslation.objects.filter(
            article=article,
            language_code="it",
        ).exists()

    @staticmethod
    def _form_data(*, include_italian: bool = True) -> dict[str, str]:
        translations = [("en-us", DEFAULT_TRANSLATION)]
        if include_italian:
            translations.append(("it", ITALIAN_TRANSLATION))
        return {
            get_translation_form_field_name(language_code, field_name): value
            for language_code, values in translations
            for field_name, value in values.items()
        }


@pytest.mark.django_db
class TestTranslationAdmin:
    def test_admin_builds_a_translatable_form_automatically(self):
        model_admin = admin.site._registry[Article]

        form_class = model_admin.get_form(cast(Any, None))

        assert issubclass(form_class, TranslatableModelForm)
        assert get_translation_form_field_name("en-us", "title") in form_class.base_fields
        assert get_translation_form_field_name("it", "title") in form_class.base_fields

    def test_custom_admin_form_must_inherit_translatable_model_form(self):
        class PlainArticleForm(forms.ModelForm):
            class Meta:
                model = Article
                fields: tuple[str, ...] = ()

        class InvalidArticleAdmin(TranslatableAdmin):
            form = PlainArticleForm

        with pytest.raises(ImproperlyConfigured, match="must inherit"):
            InvalidArticleAdmin(Article, admin.AdminSite())

    def test_foreign_key_uses_master_base_manager_for_existing_selection(self, rf):
        hidden_place = Place.all_objects.create(name="Hidden place", is_visible=False)
        section = PlaceSection.objects.create(place=hidden_place, heading="Arrival")
        request = rf.get("/admin/")
        request.user = get_user_model().objects.create_superuser(
            username="foreign-key-admin",
            email="foreign-key-admin@example.com",
            password="a-secure-password",
        )

        class PlaceSectionAdmin(TranslatableAdmin):
            autocomplete_fields = ("place",)

        model_admin = PlaceSectionAdmin(PlaceSection, admin.AdminSite())
        form = model_admin.get_form(request, section)(instance=section)

        assert form.fields["place"].queryset.filter(pk=hidden_place.pk).exists()
        assert form.initial["place"] == hidden_place.pk
        assert f'value="{hidden_place.pk}" selected' in str(form["place"])

    def test_admin_renders_and_saves_every_language(self, client):
        user_model = get_user_model()
        user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="a-secure-password",
        )
        client.force_login(user)

        response = client.get(reverse("admin:test_app_article_add"))

        assert response.status_code == 200
        assert "English (United States) (en-us)" in response.content.decode()
        assert "Italiano (it)" in response.content.decode()

        response = client.post(
            reverse("admin:test_app_article_add"),
            {**TestTranslationForm._form_data(), "_save": "Save"},
        )

        assert response.status_code == 302
        article = Article.objects.get()
        italian = cast(ArticleTranslation, article.get_translation("it"))
        assert italian.title == ITALIAN_TRANSLATION["title"]
