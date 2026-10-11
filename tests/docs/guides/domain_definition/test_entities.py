"""Check what docs/guides/domain-definition/entities.md says about entities.

``007.py`` defines the ``Post`` and ``Comment`` example under "Definition".
The ``entities/`` examples each define their own ``Order`` aggregate with the
entity a section of the page shows. Each test loads its example fresh, so
every test gets its own domain and its own memory store.
"""

from decimal import Decimal

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError, IncorrectUsageError, ValidationError
from protean.fields import HasMany, HasOne, String
from protean.utils.reflection import attributes, declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def activated(domain):
    domain.init(traverse=False)
    return domain.domain_context()


def test_entities_guide_comment_links_to_its_post():
    example = load_example("guides/domain-definition/007.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context():
        post = example.Post(name="Hello", created_on="2024-01-01")
        comment = example.Comment(content="Nice", post=post)

    assert comment.post_id == post.id
    assert example.Comment.meta_.part_of is example.Post


def test_an_entity_without_part_of_raises_incorrect_usage_error():
    publishing = Domain()

    with pytest.raises(
        IncorrectUsageError,
        match="^Entity `Comment` needs to be associated with an Aggregate$",
    ):

        @publishing.entity
        class Comment:
            content = String(max_length=500)


def test_the_abstract_option_raises_configuration_error():
    domain = Domain()

    with pytest.raises(ConfigurationError, match="Unknown option.*abstract"):

        @domain.entity(part_of="Order", abstract=True)
        class LineItem:
            sku = String(max_length=64)


def test_entity_indexes_are_declared_on_the_entity():
    example = load_example("guides/domain-definition/entities/001.py")

    with activated(example.domain):
        (index,) = example.LineItem.meta_.indexes
        order = example.Order(
            number="ORD-1", line_items=[example.LineItem(sku="SKU-1", quantity=2)]
        )

    assert index.fields == ("sku",)
    assert index.unique is True
    assert order.line_items[0].sku == "SKU-1"


def test_a_base_class_shares_its_fields_with_the_concrete_entity(capsys):
    example = load_example("guides/domain-definition/entities/002.py")

    assert (
        capsys.readouterr().out == "['quantity', 'unit_price', 'id', 'sku', 'order']\n"
    )

    with activated(example.domain):
        item = example.ProductLineItem(
            sku="SKU-1", quantity=3, unit_price=Decimal("2.50")
        )
        registered = example.domain.registry.entities

    assert item.subtotal == Decimal("7.50")
    assert all(record.cls is not example.BaseLineItem for record in registered.values())


def test_an_event_raised_by_an_entity_lands_on_the_aggregate():
    example = load_example("guides/domain-definition/entities/003.py")

    with activated(example.domain):
        order = example.Order(
            number="ORD-1",
            items=[example.OrderItem(product_name="Widget", quantity=2)],
        )
        item = order.items[0]
        item.update_quantity(5)

    (event,) = order._events
    assert isinstance(event, example.OrderItemQuantityChanged)
    assert event.order_id == str(order.id)
    assert event.product_name == "Widget"
    assert event.new_quantity == 5
    assert item.quantity == 5
    assert item._events == []


def test_the_entity_invariant_rejects_a_non_positive_quantity():
    example = load_example("guides/domain-definition/entities/004.py")

    with activated(example.domain):
        with pytest.raises(ValidationError) as exc:
            example.OrderItem(product_name="Widget", quantity=0)
        item = example.OrderItem(product_name="Widget", quantity=1)

    assert exc.value.messages == {"quantity": ["Quantity must be positive"]}
    assert item.quantity == 1


def test_defaults_computes_the_line_total():
    example = load_example("guides/domain-definition/entities/005.py")

    with activated(example.domain):
        computed = example.OrderItem(
            product_name="Widget", quantity=3, unit_price=Decimal("2.5")
        )
        defaulted = example.OrderItem(product_name="Widget", unit_price=Decimal("2.5"))
        given = example.OrderItem(
            product_name="Widget",
            quantity=4,
            unit_price=Decimal("2.5"),
            line_total=Decimal(1),
        )

    assert computed.line_total == Decimal("7.5")
    assert defaulted.quantity == 1
    assert defaulted.line_total == Decimal("2.5")
    assert given.line_total == Decimal(1)


def test_adding_the_aggregate_persists_its_entities():
    example = load_example("guides/domain-definition/entities/006.py")

    with example.domain.domain_context():
        saved = example.domain.repository_for(example.Order).get(example.order.id)

    assert saved.number == "ORD-1"
    assert [(item.product_name, item.quantity) for item in saved.items] == [
        ("Widget", 2)
    ]
    assert saved.items[0].id == example.order.items[0].id


def test_an_entity_navigates_back_to_its_aggregate():
    example = load_example("guides/domain-definition/entities/006.py")

    assert example.order_item is example.order.items[0]
    assert example.parent_order is example.order
    assert example.order_id == example.order.id


def test_from_value_object_builds_an_entity(capsys):
    example = load_example("guides/domain-definition/entities/007.py")

    assert capsys.readouterr().out == "Widget 2\n"
    assert isinstance(example.item, example.OrderItem)
    assert example.item.id is not None


def test_the_handler_builds_entities_from_the_command_value_objects():
    example = load_example("guides/domain-definition/entities/007.py")

    with activated(example.domain):
        example.domain.process(
            example.PlaceOrder(
                number="ORD-7",
                items=[
                    {"product_name": "Widget", "quantity": 2},
                    {"product_name": "Gadget", "quantity": 1},
                ],
            ),
            asynchronous=False,
        )
        repo = example.domain.repository_for(example.Order)
        order = repo.find_by(number="ORD-7")

    assert sorted((i.product_name, i.quantity) for i in order.items) == [
        ("Gadget", 1),
        ("Widget", 2),
    ]
    assert len({item.id for item in order.items}) == 2


def test_an_entity_gets_a_reference_to_its_aggregate():
    example = load_example("guides/domain-definition/entities/008.py")

    with activated(example.domain):
        order = example.Order(number="ORD-1")
        item = example.OrderItem(product_name="Widget", quantity=2)
        order.add_items(item)

    assert "order" in declared_fields(example.OrderItem)
    assert "order_id" in attributes(example.OrderItem)
    assert item.order_id == order.id
    assert item.order is order


def test_an_explicit_reference_renames_the_shadow_field():
    example = load_example("guides/domain-definition/entities/009.py")

    with activated(example.domain):
        order = example.Order(number="ORD-1")
        item = example.OrderItem(product_name="Widget", quantity=2)
        order.add_items(item)

    assert "parent_order_id" in attributes(example.OrderItem)
    assert "order_id" not in attributes(example.OrderItem)
    assert item.parent_order_id == order.id
    assert item.order is order


class TestCommonErrors:
    def test_an_entity_cannot_enclose_an_aggregate(self):
        domain = Domain(name="Publishing")

        @domain.aggregate
        class Author:
            name = String()

        @domain.aggregate
        class Post:
            name = String()

        @domain.entity(part_of=Post)
        class Comment:
            content = String()
            author = HasOne(Author)

        with pytest.raises(
            IncorrectUsageError,
            match="Field `author` in `Comment` is not linked to an Entity class",
        ):
            domain.init(traverse=False)

    def test_a_missing_required_field_raises_validation_error(self):
        domain = Domain(name="Publishing")

        @domain.aggregate
        class Post:
            name = String()

        @domain.entity(part_of=Post)
        class Comment:
            content = String(required=True)

        with activated(domain):
            with pytest.raises(ValidationError) as exc:
                Comment()

        assert exc.value.messages == {"content": ["is required"]}

    def test_raising_an_event_of_another_aggregate_raises_configuration_error(self):
        domain = Domain(name="Publishing")

        @domain.aggregate
        class Post:
            name = String()
            comments = HasMany("Comment")

        @domain.entity(part_of=Post)
        class Comment:
            content = String()

            def flag(self):
                self.raise_(AuthorFlagged(reason="spam"))

        @domain.aggregate
        class Author:
            name = String()

        @domain.event(part_of=Author)
        class AuthorFlagged:
            reason = String()

        with activated(domain):
            comment = Comment(content="Buy now")
            Post(name="Hello", comments=[comment])

            with pytest.raises(
                ConfigurationError,
                match="Event `AuthorFlagged` is not associated with aggregate `Post`",
            ):
                comment.flag()


def test_a_plain_mixin_contributes_no_fields():
    domain = Domain(name="Publishing")

    class Tagged:
        tag = String()

    @domain.aggregate
    class Post:
        name = String()

    @domain.entity(part_of=Post)
    class Comment(Tagged):
        content = String()

    domain.init(traverse=False)

    assert "tag" not in declared_fields(Comment)
    assert "content" in declared_fields(Comment)
