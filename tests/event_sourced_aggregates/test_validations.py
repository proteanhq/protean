import pytest

from pydantic import Field

from protean.exceptions import NotSupportedError


def test_exception_on_multiple_identifiers(test_domain):
    with pytest.raises(NotSupportedError) as exc:

        @test_domain.aggregate(is_event_sourced=True)
        class Person:
            email: str = Field(json_schema_extra={"identifier": True})
            username: str = Field(json_schema_extra={"identifier": True})

    assert "Only one identifier field is allowed" in exc.value.args[0]["_entity"][0]
