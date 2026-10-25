import pytest

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import String

domain = Domain(name="Accounts")


@domain.value_object
class Email:
    address = String(max_length=254, required=True)

    @invariant.post
    def address_has_one_at_sign(self):
        if self.address.count("@") != 1:
            raise ValidationError({"address": ["Email needs exactly one @"]})


@pytest.fixture(scope="module", autouse=True)
def accounts():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:parametrize]
@pytest.mark.parametrize("address", ["ana@example.com", "a.b+tag@example.org"])
def test_a_valid_address_is_accepted(address):
    assert Email(address=address).address == address


@pytest.mark.parametrize("address", ["ana.example.com", "ana@@example.com"])
def test_an_address_without_exactly_one_at_sign_is_rejected(address):
    with pytest.raises(ValidationError) as exc:
        Email(address=address)

    assert exc.value.messages == {"address": ["Email needs exactly one @"]}


# --8<-- [end:parametrize]
