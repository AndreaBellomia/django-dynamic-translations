from django.contrib import admin

from django_dynamic_translations.admin import TranslatableAdmin

from .models import Article


@admin.register(Article)
class ArticleAdmin(TranslatableAdmin):
    list_display = ("title", "slug")
    search_fields = ("translations__title", "translations__slug")
