import pytest
from pydantic import Field as PydanticField

from protean.core.entity import BaseEntity
from protean.exceptions import ValidationError
from protean.utils.reflection import fields


class TestFields:
    def test_lists_can_be_mandatory(self):
        class Lottery(BaseEntity):
            jackpot: bool | None = None
            numbers: list[int]

        with pytest.raises(ValidationError) as exc:
            Lottery(jackpot=True)

        assert exc.value.messages == {"numbers": ["is required"]}

    def test_dicts_can_be_mandatory(self):
        class Lottery(BaseEntity):
            jackpot: bool | None = None
            numbers: dict

        with pytest.raises(ValidationError) as exc:
            Lottery(jackpot=True)

        assert exc.value.messages == {"numbers": ["is required"]}

    def test_field_description(self):
        class Lottery(BaseEntity):
            jackpot: bool | None = PydanticField(
                default=None, description="Jackpot won or not"
            )

        assert fields(Lottery)["jackpot"].description == "Jackpot won or not"

    def test_field_default_description(self):
        class Lottery(BaseEntity):
            jackpot: bool | None = None

        # By default, description is not auto-set.
        assert fields(Lottery)["jackpot"].description is None
