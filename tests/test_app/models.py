from typing import TYPE_CHECKING

from django.db import models

from django_dynamic_translations.models import (
    BaseTranslation,
    TranslatableModel,
    TranslatedField,
)


class Category(TranslatableModel):
    name = TranslatedField[str](models.CharField(max_length=100))


class Article(TranslatableModel):
    title = TranslatedField[str](models.CharField(max_length=255))
    slug = TranslatedField[str](models.SlugField(max_length=255, unique=True))
    body = TranslatedField[str](models.TextField())
    categories = models.ManyToManyField(Category, blank=True, related_name="articles")

    def __str__(self) -> str:
        return self.title


if TYPE_CHECKING:

    class ArticleTranslation(BaseTranslation):
        article: Article
        title: str
        slug: str
        body: str

    class CategoryTranslation(BaseTranslation):
        category: Category
        name: str
