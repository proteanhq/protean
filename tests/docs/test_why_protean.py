"""Check what docs/why-protean.md says about Protean.

Each test loads its example fresh, so every test gets its own domain and its
own memory store.
"""

import json

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def activated(domain):
    domain.init(traverse=False)
    return domain.domain_context()


def test_to_ir_returns_a_json_ready_description_of_the_domain():
    example = load_example("why-protean/001.py")

    assert example.ir["domain"]["name"] == example.domain.name
    assert "AGGREGATE" in example.ir["elements"]
    assert json.loads(json.dumps(example.ir)) == example.ir


class TestAlwaysValid:
    @pytest.fixture
    def example(self):
        module = load_example("why-protean/002.py")
        with activated(module.domain):
            yield module

    def test_a_placed_order_without_items_is_rejected(self, example):
        with pytest.raises(ValidationError) as exc:
            example.Order(customer_id="cust-1", status="confirmed")

        assert exc.value.messages == {"items": ["Order must have at least one item"]}

    def test_a_draft_order_without_items_is_accepted(self, example):
        order = example.Order(customer_id="cust-1")

        assert order.status == "draft"

    def test_a_placed_order_with_items_is_accepted(self, example):
        order = example.Order(
            customer_id="cust-1",
            status="confirmed",
            items=[example.OrderItem(product_id="prod-1")],
        )

        assert order.status == "confirmed"

    def test_a_change_that_breaks_the_rule_is_rejected(self, example):
        order = example.Order(customer_id="cust-1")

        with pytest.raises(ValidationError, match="Order must have at least one item"):
            order.status = "confirmed"

        assert order.status == "draft"


class TestProgressiveArchitecture:
    @pytest.fixture
    def example(self):
        module = load_example("why-protean/003.py")
        with activated(module.domain):
            yield module

    def test_the_application_service_creates_and_stores_a_post(self, example):
        post_id = example.PostService().create_post(title="Hello", body="World")

        post = example.domain.repository_for(example.Post).get(post_id)
        assert (post.title, post.body, post.status) == ("Hello", "World", "DRAFT")

    def test_the_command_handler_publishes_the_post(self, example):
        post_id = example.PostService().create_post(title="Hello", body="World")

        example.domain.process(example.PublishPost(post_id=post_id), asynchronous=False)

        post = example.domain.repository_for(example.Post).get(post_id)
        assert post.status == "PUBLISHED"


def test_the_event_sourced_account_applies_deposits():
    example = load_example("why-protean/004.py")

    with activated(example.domain):
        account = example.Account()
        account.raise_(example.Deposited(amount=50.0))
        account.raise_(example.Deposited(amount=25.5))

    assert example.Account.meta_.is_event_sourced is True
    assert account.balance == 75.5


def test_a_bare_domain_uses_in_memory_adapters():
    example = load_example("why-protean/005.py")
    config = example.domain.config

    assert config["databases"]["default"]["provider"] == "memory"
    assert config["brokers"]["default"]["provider"] == "inline"
    assert config["event_store"]["provider"] == "memory"
    assert config["caches"]["default"]["provider"] == "memory"
