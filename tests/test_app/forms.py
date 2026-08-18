from django_dynamic_translations.forms import TranslatableModelForm

from .models import Article


class ArticleForm(TranslatableModelForm):
    class Meta:
        model = Article
        fields: tuple[str, ...] = ()
