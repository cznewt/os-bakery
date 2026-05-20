# Contributing

## Local setup

```sh
# Python 3.12+
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Code style

- `ruff format .` for formatting (Black-equivalent).
- `ruff check .` for lint.
- Imports sorted via ruff `I` ruleset.
- Type hints on public functions; we run `python -m mypy` opportunistically (no CI gate yet).

## Tests

```sh
pytest
```

Unit tests live next to the code (`<app>/tests.py`). Integration tests for the orchestrator should mock out the actual mount + salt-call but exercise the surrounding flow (pillar materialisation, packing, publish).

## Migrations

```sh
python manage.py makemigrations
python manage.py migrate
```

Squashes are welcome before tagging releases; don't squash mid-feature-branch.

## Commit / PR conventions

- One logical change per PR.
- Conventional-ish commits: `feat: …`, `fix: …`, `docs: …`, `refactor: …`.
- Reference the matching `docs/` page when the change is user-visible.

## Adding a new OS

See [`operations.md`](operations.md#adding-a-new-operating-system).

## Adding a new Salt formula

See [`salt.md`](salt.md#adding-a-new-formula).
