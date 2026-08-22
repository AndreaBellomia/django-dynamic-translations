import pytest
from django.utils import translation
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import ReadOnlyModelViewSet

from django_dynamic_translations.rest_framework import (
    TranslatableLookupMixin,
    TranslatableModelSerializer,
)
from tests.test_app.models import Article, Category

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


class ArticleSerializer(TranslatableModelSerializer):
    class Meta:
        model = Article
        fields = "__all__"


class ArticleTitleSerializer(TranslatableModelSerializer):
    class Meta:
        model = Article
        fields = ("id", "title")


class ArticleSlugSerializer(TranslatableModelSerializer):
    class Meta:
        model = Article
        fields = ("id", "slug")


class ArticleWithoutBodySerializer(TranslatableModelSerializer):
    class Meta:
        model = Article
        exclude = ("body",)


class ArticleDepthSerializer(TranslatableModelSerializer):
    class Meta:
        model = Article
        depth = 1
        fields = "__all__"


class ArticleViewSet(TranslatableLookupMixin, ReadOnlyModelViewSet):
    queryset = Article.objects.prefetch_translations()
    serializer_class = ArticleSerializer
    lookup_field = "slug"


article_detail = ArticleViewSet.as_view({"get": "retrieve"})


class TestTranslatableModelSerializer:
    def test_all_discovers_translated_fields(self):
        serializer = ArticleSerializer()

        assert {"id", "title", "slug", "body", "categories"} <= set(serializer.fields)
        assert isinstance(serializer.fields["title"], serializers.CharField)
        assert serializer.fields["title"].max_length == 255
        assert serializer.fields["title"].read_only is False

    def test_explicit_fields_build_translated_fields(self):
        assert list(ArticleTitleSerializer().fields) == ["id", "title"]
        assert isinstance(ArticleTitleSerializer().fields["title"], serializers.CharField)

    def test_exclude_can_remove_a_translated_field(self):
        serializer = ArticleWithoutBodySerializer()

        assert "title" in serializer.fields
        assert "slug" in serializer.fields
        assert "body" not in serializer.fields

    @pytest.mark.django_db
    def test_serialization_uses_active_language_and_fallback(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()
        article = Article.objects.prefetch_translations().get()

        with translation.override("it"):
            data = ArticleSerializer(article).data

        assert data["title"] == ITALIAN_TRANSLATION["title"]
        assert data["slug"] == ITALIAN_TRANSLATION["slug"]

    @pytest.mark.django_db
    def test_create_saves_the_default_translation(self):
        serializer = ArticleSerializer(data=DEFAULT_TRANSLATION)

        assert serializer.is_valid(), serializer.errors
        article = serializer.save()

        assert article.get_translation("en-us").title == DEFAULT_TRANSLATION["title"]

    @pytest.mark.django_db
    def test_update_saves_the_active_translation(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()

        with translation.override("it"):
            serializer = ArticleTitleSerializer(
                article,
                data={"title": "La Costiera Amalfitana"},
                partial=True,
            )
            assert serializer.is_valid(), serializer.errors
            serializer.save()

        article.clear_translation_cache()
        assert article.get_translation("it").title == "La Costiera Amalfitana"

    @pytest.mark.django_db
    def test_nested_serializers_discover_related_translated_fields(self):
        category = Category.objects.create(name="Coast")
        category.set_translation("it", name="Costa")
        category.save()
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.categories.add(category)
        article = Article.objects.prefetch_translations("categories").get()

        with translation.override("it"):
            data = ArticleDepthSerializer(article).data

        assert data["categories"][0]["name"] == "Costa"

    @pytest.mark.django_db
    def test_unique_validator_excludes_the_active_translation_on_update(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()

        with translation.override("it"):
            serializer = ArticleSlugSerializer(
                article,
                data={"slug": ITALIAN_TRANSLATION["slug"]},
                partial=True,
            )

            assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
class TestTranslatableLookupMixin:
    def test_retrieve_resolves_translated_lookup_in_active_language(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        article.set_translation("it", **ITALIAN_TRANSLATION)
        article.save()
        request = APIRequestFactory().get("/articles/costiera-amalfitana/")

        with translation.override("it"):
            response = article_detail(request, slug=ITALIAN_TRANSLATION["slug"])

        assert response.status_code == 200
        assert response.data["id"] == article.pk
        assert response.data["slug"] == ITALIAN_TRANSLATION["slug"]

    def test_missing_translated_lookup_returns_not_found(self):
        Article.objects.create(**DEFAULT_TRANSLATION)
        request = APIRequestFactory().get("/articles/not-found/")

        response = article_detail(request, slug="not-found")

        assert response.status_code == 404

    def test_retrieve_uses_default_language_fallback(self):
        article = Article.objects.create(**DEFAULT_TRANSLATION)
        request = APIRequestFactory().get("/articles/amalfi-coast/")

        with translation.override("it"):
            response = article_detail(request, slug=DEFAULT_TRANSLATION["slug"])

        assert response.status_code == 200
        assert response.data["id"] == article.pk
        assert response.data["slug"] == DEFAULT_TRANSLATION["slug"]
