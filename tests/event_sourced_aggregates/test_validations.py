import pytest

from protean.exceptions import NotSupportedError
from protean.fields import String


def test_exception_on_multiple_identifiers(test_domain):
    with pytest.raises(NotSupportedError) as exc:

        @test_domain.event_sourced_aggregate
        class Person:
            email = String(identifier=True)
            username = String(identifier=True)

    assert "Only one identifier field is allowed" in exc.value.args[0]["_entity"][0]
