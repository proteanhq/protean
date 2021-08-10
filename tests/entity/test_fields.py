import pytest

from protean.core.entity import BaseEntity
from protean.core.field.basic import Boolean, Dict, Integer, List
from protean.exceptions import ValidationError


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
