import pytest

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    status = String(default="DRAFT")

    def place(self):
        self.status = "PLACED"

    def cancel(self):
        if self.status != "PLACED":
            raise ValidationError({"status": ["Only a placed order can be cancelled"]})
        self.status = "CANCELLED"


@pytest.fixture(scope="module", autouse=True)
def ordering():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:one_behaviour]
def test_placing_an_order_marks_it_placed():
    order = Order()

    order.place()

    assert order.status == "PLACED"


def test_cancelling_a_placed_order_marks_it_cancelled():
    order = Order()
    order.place()

    order.cancel()

    assert order.status == "CANCELLED"


def test_a_draft_order_cannot_be_cancelled():
    order = Order()

    with pytest.raises(ValidationError) as exc:
        order.cancel()

    assert exc.value.messages == {"status": ["Only a placed order can be cancelled"]}


# --8<-- [end:one_behaviour]
