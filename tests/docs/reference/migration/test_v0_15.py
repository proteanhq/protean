"""Check what docs/reference/migration/v0-15.md says about upgrading to 0.15.

Each test loads the after-code of one migration step fresh, so every test gets
its own domain. Where the page says the 0.14 code now fails, a test builds that
code and checks the error.
"""

import pytest

from protean import Domain, apply
from protean._deprecation import RemovedInProtean019Warning
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Float
from tests.docs.support import load_example
from tests.shared import ELASTICSEARCH_URI

pytestmark = pytest.mark.no_test_domain


def activated(domain):
    domain.init(traverse=False)
    return domain.domain_context()


def test_a_value_object_list_holds_and_stores_value_objects():
    example = load_example("reference/migration/v0-15/001.py")

    with activated(example.domain):
        order = example.Order(
            items=[example.OrderItem(sku="SKU-1", quantity=2)],
        )
        example.domain.repository_for(example.Order).add(order)
        saved = example.domain.repository_for(example.Order).get(order.id)

    assert order.to_dict()["items"] == [{"sku": "SKU-1", "quantity": 2}]
    assert saved.items == [example.OrderItem(sku="SKU-1", quantity=2)]


def test_a_value_object_list_validates_each_item():
    example = load_example("reference/migration/v0-15/001.py")

    with activated(example.domain):
        with pytest.raises(ValidationError, match="sku"):
            example.Order(items=[{"quantity": 2}])


def test_a_value_object_takes_only_its_own_fields():
    example = load_example("reference/migration/v0-15/002.py")

    assert example.address.street == "123 Main"
    assert example.address.city == "NYC"


def test_an_extra_keyword_on_a_value_object_raises_validation_error():
    example = load_example("reference/migration/v0-15/002.py")

    with pytest.raises(ValidationError) as exc_info:
        example.Address(street="123 Main", city="NYC", extra_field="ignored")

    assert exc_info.value.messages == {
        "extra_field": ["Extra inputs are not permitted"]
    }


def test_publishing_through_the_broker_puts_the_message_on_the_stream():
    example = load_example("reference/migration/v0-15/003.py")

    with activated(example.domain):
        example.publish_order_event({"order_id": "ord-1", "total": 42})
        messages = example.domain.brokers["default"].read(
            "order_events", "order-readers", 1
        )

    assert [payload for _, payload in messages] == [{"order_id": "ord-1", "total": 42}]


def test_domain_publish_is_gone():
    example = load_example("reference/migration/v0-15/003.py")

    with pytest.raises(AttributeError, match="publish"):
        example.domain.publish("order_events", {"order_id": "ord-1"})


def load_account_example():
    # The 0.15 page spells the option `is_event_sourced`, which later releases
    # deprecate in favour of `event_sourced`.
    with pytest.warns(RemovedInProtean019Warning, match="is_event_sourced"):
        return load_example("reference/migration/v0-15/004.py")


def test_apply_changes_state_on_the_live_path():
    example = load_account_example()

    with activated(example.domain):
        account = example.Account.open(100.0)
        account.withdraw(30.0)

    assert account.balance == 70.0


def test_apply_rebuilds_the_same_state_on_replay():
    example = load_account_example()

    with activated(example.domain):
        account = example.Account.open(100.0)
        account.withdraw(30.0)
        account.withdraw(20.0)
        example.domain.repository_for(example.Account).add(account)

        replayed = example.domain.repository_for(example.Account).get(account.id)

    assert replayed.balance == 50.0


def test_a_missing_apply_handler_raises_incorrect_usage_error_in_raise():
    domain = Domain(name="Banking")

    @domain.event(part_of="Account")
    class Withdrawn:
        amount = Float(required=True)

    @domain.event(part_of="Account")
    class Deposited:
        amount = Float(required=True)

    @domain.aggregate(event_sourced=True)
    class Account:
        balance = Float(default=0.0)

        def deposit(self, amount):
            self.raise_(Deposited(amount=amount))

        @apply
        def on_withdrawn(self, event: Withdrawn):
            self.balance -= event.amount

    with activated(domain):
        account = Account()
        with pytest.raises(IncorrectUsageError, match="Deposited"):
            account.deposit(10.0)


@pytest.fixture
def search_example(monkeypatch):
    monkeypatch.setenv("ELASTICSEARCH_HOST", ELASTICSEARCH_URI["hosts"][0])
    example = load_example("reference/migration/v0-15/005.py")
    example.domain.config["databases"]["elasticsearch"]["NAMESPACE_PREFIX"] = (
        "docs-migration"
    )
    example.domain.init(traverse=False)
    yield example
    with example.domain.domain_context():
        example.domain.providers["elasticsearch"]._drop_database_artifacts()


@pytest.mark.elasticsearch
def test_recreated_indexes_map_strings_as_keywords_and_keep_the_custom_model(
    search_example,
):
    search_example.recreate_indexes()

    with search_example.domain.domain_context():
        repo = search_example.domain.repository_for(search_example.Article)
        index = repo._database_model._index._name
        connection = search_example.domain.providers["elasticsearch"].get_connection()
        properties = connection.indices.get_mapping(index=index)[index]["mappings"][
            "properties"
        ]

    assert properties["title"] == {
        "type": "text",
        "analyzer": "standard",
        "fields": {"keyword": {"type": "keyword"}},
    }
    assert properties["category"] == {"type": "keyword"}
