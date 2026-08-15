"""A failed value object invariant carries VALUE_OBJECT_INVARIANT_FAILED (or the
author's code) on its ValidationError.

Value objects run only post-invariants, at construction, so the default code is
always VALUE_OBJECT_INVARIANT_FAILED.
"""

import pickle

import pytest

from protean.core.entity import invariant
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Float, String
from protean.ir.diagnostics import DiagnosticCode, resolve

VO_CODE = DiagnosticCode.VALUE_OBJECT_INVARIANT_FAILED.value


class Balance(BaseValueObject):
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    @invariant.post
    def amount_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Balance cannot be negative"]})


class Email(BaseValueObject):
    address: String(required=True)

    @invariant.post(code="EMAIL_MALFORMED")
    def has_at_sign(self):
        if "@" not in self.address:
            raise ValidationError({"address": ["Address is malformed"]})


class Coordinate(BaseValueObject):
    lat: Float(required=True)
    lng: Float(required=True)

    @invariant.post(code="LAT_OUT_OF_RANGE")
    def lat_in_range(self):
        if not -90 <= self.lat <= 90:
            raise ValidationError({"lat": ["Latitude out of range"]})

    @invariant.post(code="LNG_OUT_OF_RANGE")
    def lng_in_range(self):
        if not -180 <= self.lng <= 180:
            raise ValidationError({"lng": ["Longitude out of range"]})


class Weight(BaseValueObject):
    grams: Float(required=True)

    @invariant.post(code=DiagnosticCode.VALUE_OBJECT_INVARIANT_FAILED)
    def grams_non_negative(self):
        if self.grams < 0:
            raise ValidationError({"grams": ["Weight cannot be negative"]})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Balance)
    test_domain.register(Email)
    test_domain.register(Coordinate)
    test_domain.register(Weight)
    test_domain.init(traverse=False)


class TestValueObjectInvariantCode:
    def test_failure_carries_the_value_object_code(self):
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USD", amount=-100.0)

        assert exc.value.code == VO_CODE
        assert exc.value.codes == [VO_CODE]
        assert exc.value.location == "Balance"
        # The errors dict is unchanged by the code.
        assert exc.value.messages == {"amount": ["Balance cannot be negative"]}

    def test_rationale_and_fix_resolve_from_the_registry(self):
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USD", amount=-100.0)

        meta = resolve(DiagnosticCode.VALUE_OBJECT_INVARIANT_FAILED)
        assert exc.value.rationale == meta.rationale
        assert exc.value.fix == meta.fix

    def test_custom_code_is_carried(self):
        with pytest.raises(ValidationError) as exc:
            Email(address="nope")

        assert exc.value.code == "EMAIL_MALFORMED"
        assert exc.value.codes == ["EMAIL_MALFORMED"]

    def test_a_valid_value_object_constructs_without_a_coded_error(self):
        # The negative case: valid input raises nothing, so no code is produced.
        vo = Balance(currency="USD", amount=100.0)
        assert vo.amount == 100.0

    def test_a_diagnostic_code_member_is_carried_as_its_value(self):
        with pytest.raises(ValidationError) as exc:
            Weight(grams=-1.0)

        assert exc.value.codes == [VO_CODE]
        assert type(exc.value.codes[0]) is str

    def test_two_invariants_failing_together_carry_both_codes(self):
        with pytest.raises(ValidationError) as exc:
            Coordinate(lat=100.0, lng=200.0)

        assert exc.value.codes == ["LAT_OUT_OF_RANGE", "LNG_OUT_OF_RANGE"]
        assert exc.value.code is None
        assert set(exc.value.messages) == {"lat", "lng"}

    def test_codes_survive_a_pickle_round_trip(self):
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USD", amount=-1.0)

        restored = pickle.loads(pickle.dumps(exc.value))

        assert type(restored) is ValidationError
        assert restored.code == VO_CODE
        assert restored.codes == [VO_CODE]
        assert restored.location == "Balance"
