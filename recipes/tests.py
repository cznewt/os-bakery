from __future__ import annotations

import pytest

from catalog.models import OperatingSystem
from recipes.models import Recipe, RecipeOption, RecipeVersion


@pytest.mark.django_db
def test_only_one_current_version_per_recipe() -> None:
    os_ = OperatingSystem.objects.create(slug="batocera", name="Batocera", kind="retro")
    recipe = Recipe.objects.create(slug="arcade", name="Arcade", operating_system=os_)

    v1 = RecipeVersion.objects.create(recipe=recipe, version="1.0.0", is_current=True)
    v2 = RecipeVersion.objects.create(recipe=recipe, version="1.1.0", is_current=True)

    v1.refresh_from_db()
    v2.refresh_from_db()
    assert v1.is_current is False
    assert v2.is_current is True


@pytest.mark.django_db
def test_recipe_option_uniqueness_per_recipe() -> None:
    os_ = OperatingSystem.objects.create(slug="raspios", name="Raspberry Pi OS", kind="iot")
    recipe = Recipe.objects.create(slug="kiosk", name="Kiosk", operating_system=os_)
    RecipeOption.objects.create(recipe=recipe, key="hostname", label="Hostname", kind="string")
    with pytest.raises(Exception):
        RecipeOption.objects.create(recipe=recipe, key="hostname", label="Hostname 2")
