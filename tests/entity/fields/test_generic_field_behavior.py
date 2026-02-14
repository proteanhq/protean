import pytest

from protean.core.entity import BaseEntity
from protean.exceptions import ValidationError
from protean.fields import Boolean, Dict, Integer, List
from protean.utils.reflection import fields


class TestFields:
    def test_lists_can_be_mandatory(self):
        class Lottery(BaseEntity):
            jackpot = Boolean()
            numbers = List(content_type=Integer, required=True)

        with pytest.raises(ValidationError) as exc:
            Lottery(jackpot=True)

        assert exc.value.messages == {"numbers": ["is required"]}

    def test_dicts_can_be_mandatory(self):
        class Lottery(BaseEntity):
            jackpot = Boolean()
            numbers = Dict(required=True)

        with pytest.raises(ValidationError) as exc:
            Lottery(jackpot=True)

        assert exc.value.messages == {"numbers": ["is required"]}

    def test_field_description(self):
        class Lottery(BaseEntity):
            jackpot = Boolean(description="Jackpot won or not")

        assert fields(Lottery)["jackpot"].description == "Jackpot won or not"

    def test_field_default_description(self):
        class Lottery(BaseEntity):
            jackpot = Boolean()

        # By default, description is not auto-set.
        assert fields(Lottery)["jackpot"].description is None
