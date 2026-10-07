"""The examples on the custom fields reference behave as the page says."""

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example


def test_custom_brand_parses_a_hex_string_into_a_color():
    example = load_example("guides/domain-definition/fields/custom-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        palette = example.Palette(name="sky", brand="#3366ff")

    assert isinstance(palette.brand, example.Color)
    assert palette.brand == example.Color("#3366FF")
    assert palette.brand.hex == "#3366FF"


def test_custom_brand_passes_an_existing_color_through():
    example = load_example("guides/domain-definition/fields/custom-fields/001.py")
    example.domain.init(traverse=False)
    color = example.Color("#3366FF")

    with example.domain.domain_context():
        palette = example.Palette(name="sky", brand=color)

    assert palette.brand is color


def test_custom_brand_rejects_a_value_that_is_not_a_hex_color():
    example = load_example("guides/domain-definition/fields/custom-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Palette(name="sky", brand="not-a-color")

    assert "brand" in exc.value.messages


def test_custom_brand_round_trips_through_the_repository_and_filters():
    example = load_example("guides/domain-definition/fields/custom-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Palette)
        palette = example.Palette(name="sky", brand="#3366ff")
        repo.add(palette)
        reloaded = repo.get(palette.id)
        by_color = repo.query.filter(brand=example.Color("#3366FF")).all().items
        by_string = repo.query.filter(brand="#3366FF").all().items

    assert reloaded.brand == example.Color("#3366FF")
    assert [p.id for p in by_color] == [palette.id]
    assert [p.id for p in by_string] == [palette.id]


def test_the_conformance_example_passes():
    example = load_example("guides/domain-definition/fields/custom-fields/002.py")

    example.test_color_field_conformance()
