import django_filters
import pytest
from django import forms
from django.utils import translation

from django_dynamic_translations.django_filters import TranslatableFilterSet
from tests.test_app.models import Article


class ArticleFilter(TranslatableFilterSet):
    class Meta:
        model = Article
        fields = {
            "title": ["exact", "icontains"],
            "categories": ["exact"],
        }


class DeclaredArticleFilter(TranslatableFilterSet):
    title = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = Article
        fields = ("title",)


class AllArticleFieldsFilter(TranslatableFilterSet):
    class Meta:
        model = Article
        fields = "__all__"


class ExcludedArticleFieldsFilter(TranslatableFilterSet):
    class Meta:
        model = Article
        exclude = ("body",)


@pytest.mark.django_db
class TestTranslatableFilterSet:
    def test_generates_filters_from_translated_model_fields(self):
        filterset = ArticleFilter()

        assert set(filterset.filters) == {"title", "title__icontains", "categories"}
        assert isinstance(filterset.filters["title"], django_filters.CharFilter)
        assert isinstance(filterset.form.fields["title"], forms.CharField)

    def test_all_discovers_translated_fields(self):
        assert {"title", "slug", "body", "categories"} <= set(AllArticleFieldsFilter.base_filters)

    def test_exclude_discovers_other_translated_fields(self):
        assert {"title", "slug", "categories"} <= set(ExcludedArticleFieldsFilter.base_filters)
        assert "body" not in ExcludedArticleFieldsFilter.base_filters

    def test_filters_translated_field_in_active_language(self):
        article = Article.objects.create(
            title="Amalfi Coast",
            slug="amalfi-coast",
            body="English body",
        )
        article.set_translation(
            "it",
            title="Costiera Amalfitana",
            slug="costiera-amalfitana",
            body="Corpo italiano",
        )
        article.save()
        Article.objects.create(title="Dolomites", slug="dolomites", body="English body")

        with translation.override("it"):
            filterset = ArticleFilter(
                {"title__icontains": "amalfitana"},
                queryset=Article.objects.all(),
            )

            assert list(filterset.qs) == [article]

    def test_declared_filter_uses_translated_lookup(self):
        article = Article.objects.create(
            title="Amalfi Coast",
            slug="amalfi-coast",
            body="English body",
        )

        filterset = DeclaredArticleFilter(
            {"title": "amalfi"},
            queryset=Article.objects.all(),
        )

        assert list(filterset.qs) == [article]

    def test_keeps_non_translated_filters(self):
        category_filter = ArticleFilter.base_filters["categories"]

        assert isinstance(category_filter, django_filters.ModelMultipleChoiceFilter)
