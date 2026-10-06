"""An inner ``class Meta`` on an aggregate or entity configures nothing.

Configuration goes through decorator (or ``register``) options. The skills and
the entities guide teach only that form, so these tests pin the behavior they
describe: the option changes ``meta_``, and an inner ``Meta`` with the same
setting leaves the default in place.
"""

from protean.fields import HasMany, String


def test_inner_meta_on_an_aggregate_is_ignored(test_domain):
    @test_domain.aggregate
    class Ledger:
        name = String()

        class Meta:
            schema_name = "custom_ledgers"
            provider = "secondary"

    test_domain.init(traverse=False)

    assert Ledger.meta_.schema_name == "ledger"
    assert Ledger.meta_.provider == "default"


def test_decorator_options_configure_an_aggregate(test_domain):
    @test_domain.aggregate(schema_name="custom_ledgers", provider="secondary")
    class Ledger:
        name = String()

    assert Ledger.meta_.schema_name == "custom_ledgers"
    assert Ledger.meta_.provider == "secondary"


def test_inner_meta_on_an_entity_is_ignored(test_domain):
    @test_domain.aggregate
    class Ledger:
        entries = HasMany("Entry")

    @test_domain.entity(part_of=Ledger)
    class Entry:
        memo = String()

        class Meta:
            schema_name = "custom_entries"

    test_domain.init(traverse=False)

    assert Entry.meta_.schema_name == "entry"


def test_decorator_options_configure_an_entity(test_domain):
    @test_domain.aggregate
    class Ledger:
        entries = HasMany("Entry")

    @test_domain.entity(part_of=Ledger, schema_name="custom_entries")
    class Entry:
        memo = String()

    test_domain.init(traverse=False)

    assert Entry.meta_.schema_name == "custom_entries"
