from typing import TYPE_CHECKING

from django.db import models

from django_dynamic_translations.models import (
    BaseTranslation,
    TranslatableModel,
    TranslatedField,
)


class Article(TranslatableModel):
    title = TranslatedField[str](models.CharField(max_length=255))
    slug = TranslatedField[str](models.SlugField(max_length=255))
    body = TranslatedField[str](models.TextField())

    def __str__(self) -> str:
        return self.title


if TYPE_CHECKING:

    class ArticleTranslation(BaseTranslation):
        article: Article
        title: str
        slug: str
        body: str
