"""The memory provider stores the 128-bit integer the ``uuid`` strategy makes
for an integer identity, so ``Domain.init()`` accepts that configuration."""

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import Auto, String


def test_an_integer_identity_under_the_uuid_strategy_saves_on_memory():
    domain = Domain(name="IntegerIdentityOnMemory", config={"identity_type": "integer"})

    @domain.aggregate
    class Tiny(BaseAggregate):
        title: String(max_length=50)

    domain.init(traverse=False)
    with domain.domain_context():
        tiny = Tiny(title="first")
        domain.repository_for(Tiny).add(tiny)
        loaded = domain.repository_for(Tiny).get(tiny.id)

    assert int(loaded.id) >= 2**64
    assert loaded.title == "first"


def test_an_increment_identifier_inits_on_memory():
    domain = Domain(name="IncrementOnMemory", config={"identity_type": "integer"})

    @domain.aggregate
    class Ticket(BaseAggregate):
        ticket_id: Auto(identifier=True, increment=True)

    domain.init(traverse=False)
