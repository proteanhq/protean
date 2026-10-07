"""The example on the fields reference index behaves as the page says."""

import pytest

from protean.exceptions import ValidationError
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_annotation_and_assignment_fields_both_validate():
    example = load_example("guides/domain-definition/fields/index-page/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        product = example.Product(name="Lamp", price=10.0)
        with pytest.raises(ValidationError) as name_exc:
            example.Product(price=10.0)
        with pytest.raises(ValidationError) as price_exc:
            example.Product(name="Lamp", price=-1.0)

    assert {"name", "price"} <= set(declared_fields(example.Product))
    assert product.name == "Lamp"
    assert product.price == 10.0
    assert name_exc.value.messages == {"name": ["is required"]}
    assert "price" in price_exc.value.messages
