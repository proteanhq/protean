import pytest

from protean import BaseAggregate
from protean.exceptions import NotSupportedError
from protean.fields import String


# Aggregates to test Abstraction # START #
class AbstractRole(BaseAggregate):
    foo = String(max_length=25)

    class Meta:
        abstract = True


def test_that_abstract_entities_cannot_be_initialized():
    with pytest.raises(NotSupportedError) as exc2:
        AbstractRole(name="Titan")
    assert exc2.value.args[0] == (
        "AbstractRole class has been marked abstract" " and cannot be instantiated"
    )
