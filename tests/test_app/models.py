from typing import TYPE_CHECKING, ClassVar

from django.db import models

from django_dynamic_translations.models import (
    BaseTranslation,
    TranslatableManager,
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


class VisiblePlaceManager(TranslatableManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_visible=True)


class Place(TranslatableModel):
    objects: ClassVar[TranslatableManager] = VisiblePlaceManager()
    all_objects: ClassVar[TranslatableManager] = TranslatableManager()

    name = TranslatedField[str](models.CharField(max_length=100))
    is_visible = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class PlaceSection(TranslatableModel):
    place = models.ForeignKey(Place, on_delete=models.CASCADE)
    heading = TranslatedField[str](models.CharField(max_length=100))


if TYPE_CHECKING:

    class ArticleTranslation(BaseTranslation):
        article: Article
        title: str
        slug: str
        body: str

    class CategoryTranslation(BaseTranslation):
        category: Category
        name: str

    class PlaceTranslation(BaseTranslation):
        place: Place
        name: str

    class PlaceSectionTranslation(BaseTranslation):
        placesection: PlaceSection
        heading: str
