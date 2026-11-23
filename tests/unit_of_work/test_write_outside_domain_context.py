"""A write through a repository outside a domain context names the missing context."""

import pytest

from protean import Domain
from protean.fields import Identifier

NO_CONTEXT = "No active domain context"


def _build_domain() -> tuple[Domain, type]:
    domain = Domain(name="WriteOutsideContext")

    @domain.aggregate
    class Order:
        order_id: Identifier(identifier=True)

    return domain, Order


@pytest.mark.no_test_domain
def test_add_before_init_outside_context_names_the_missing_context():
    domain, Order = _build_domain()

    with pytest.raises(AttributeError) as exc_info:
        domain.repository_for(Order).add(Order(order_id="1"))

    message = str(exc_info.value)
    assert NO_CONTEXT in message
    assert "domain.domain_context()" in message
    assert exc_info.value.name == "databases"


@pytest.mark.no_test_domain
def test_add_after_init_outside_context_names_the_missing_context():
    domain, Order = _build_domain()
    domain.init(traverse=False)

    with pytest.raises(AttributeError) as exc_info:
        domain.repository_for(Order).add(Order(order_id="1"))

    message = str(exc_info.value)
    assert NO_CONTEXT in message
    assert "domain.domain_context()" in message
    assert exc_info.value.name == "databases"


@pytest.mark.no_test_domain
def test_add_inside_context_succeeds():
    domain, Order = _build_domain()
    domain.init(traverse=False)

    with domain.domain_context():
        domain.repository_for(Order).add(Order(order_id="1"))
        assert domain.repository_for(Order).get("1").order_id == "1"
