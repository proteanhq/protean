import pytest

from protean import BaseAggregate
from protean.exceptions import NotSupportedError
from protean.fields import String


# Aggregates to test Abstraction # START #
class AbstractRole(BaseAggregate):
    foo = String(max_length=25)


def test_that_abstract_entities_cannot_be_initialized(test_domain):
    test_domain.register(AbstractRole, abstract=True)
    with pytest.raises(NotSupportedError) as exc2:
        AbstractRole(foo="Titan")
    assert exc2.value.args[0] == (
        "AbstractRole class has been marked abstract" " and cannot be instantiated"
    )
