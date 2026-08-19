# Contributing to django-dynamic-translations

Thank you for considering a contribution. Bug fixes, focused features, tests, and
documentation improvements are all welcome.

This project favors a small, explicit API and behavior that remains recognizably Django.
Before starting a large change, open an issue so the intended behavior and scope can be
agreed upon early.

## Development setup

Requirements:

- Python 3.12 or newer;
- [uv](https://docs.astral.sh/uv/);
- Git.

Clone the repository and create the development environment:

```bash
git clone https://github.com/AndreaBellomia/django-dynamic-translations.git
cd django-dynamic-translations
uv sync
```

Run the test suite to confirm the environment is working:

```bash
uv run pytest
```

The tests use a small Django application under `tests/test_app` and an in-memory SQLite
database. Test settings live in `tests/settings.py`.

## Project layout

```text
src/django_dynamic_translations/
├── models.py          # Generated translation models, aliases, managers, and querysets
├── forms.py           # All-languages ModelForm support
├── admin.py           # Django Admin integration
└── rest_framework.py  # Optional DRF serializer integration

tests/
├── test_app/          # Models and admin used by integration tests
├── test_translations.py
└── test_rest_framework.py
```

## Design principles

Contributions should preserve these principles:

- Django models and generated concrete translation tables remain the source of truth.
- Translated values should feel like normal model attributes in application code.
- The default translation must remain complete and reliably persisted.
- Language fallback must be explicit, predictable, and covered by tests.
- List and pagination workflows must avoid N+1 translation queries.
- Forms, admin, and DRF integrations should build on their framework conventions.
- Optional integrations must not become mandatory core dependencies.
- Public APIs should remain typed and documented.
- New abstraction should solve a demonstrated use case rather than anticipate one.

## Making a change

1. Create a focused branch from the current default branch.
2. Add or update tests that demonstrate the desired behavior.
3. Implement the smallest coherent change.
4. Update `README.md` when usage or public behavior changes.
5. Add an entry under `Unreleased` in `CHANGELOG.md` for user-visible changes.
6. Run the complete quality gate.

Avoid editing previously released migration behavior in downstream applications. Changes
to generated model structure should be tested against Django's migration autodetector.

## Quality gate

Run all checks before opening a pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

To apply formatting locally:

```bash
uv run ruff format .
```

Tests should cover both the successful path and relevant failure behavior. Query-related
changes should include query-count assertions where practical.

## Documentation and examples

Examples should be:

- independent from a particular product or private application;
- complete enough to copy into a small Django project;
- explicit about default-language and fallback behavior;
- efficient for queryset and serializer usage;
- consistent with the currently supported public API.

Use English for public documentation, code comments, exceptions, and changelog entries.

## Bug reports

A useful bug report includes:

- Python and Django versions;
- package version or commit;
- database backend;
- configured `LANGUAGE_CODE` and `LANGUAGES` when relevant;
- a minimal model and reproduction;
- the expected and actual behavior;
- the complete traceback.

Please remove credentials, private data, and application-specific secrets from examples.

## Feature proposals

For a new feature, describe:

- the concrete workflow it enables;
- why the existing API is insufficient;
- the expected model, query, form, admin, or serializer behavior;
- compatibility and migration considerations;
- alternatives considered.

Large cross-cutting changes should be discussed before implementation.

## Pull requests

Keep pull requests focused and explain:

- what changed;
- why the change belongs in the library;
- any compatibility implications;
- which checks were run.

Do not include unrelated formatting or refactors. Maintainers may request changes to API
shape, tests, documentation, or backwards compatibility before merging.

## License

By contributing, you agree that your contribution will be licensed under the project's
[MIT License](LICENSE).
