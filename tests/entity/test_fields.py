import pytest

from protean import BaseEntity
from protean.exceptions import ValidationError
from protean.fields import Boolean, Dict, Integer, List
from protean.reflection import fields


class TestFields:
    @pytest.mark.xfail  # To be addressed as part of https://github.com/proteanhq/protean/issues/335
    def test_list_default(self):
        class Lottery(BaseEntity):
            numbers = List(content_type=Integer)

        lottery = Lottery()
        assert lottery.numbers is not None
        assert lottery.numbers == []

    def test_lists_can_be_mandatory(self):
        class Lottery(BaseEntity):
            jackpot = Boolean()
            numbers = List(content_type=Integer, required=True)

        with pytest.raises(ValidationError) as exc:
            Lottery(jackpot=True)

        assert exc.value.messages == {"numbers": ["is required"]}

    @pytest.mark.xfail  # To be addressed as part of https://github.com/proteanhq/protean/issues/335
    def test_dict_default(self):
        class Lottery(BaseEntity):
            numbers = Dict()

        lottery = Lottery()
        assert lottery.numbers is not None
        assert lottery.numbers == {}

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

        assert fields(Lottery)["jackpot"].description == "Jackpot"
