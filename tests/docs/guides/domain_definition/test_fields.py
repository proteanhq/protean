"""The examples on the fields guide behave as the page says."""

from datetime import UTC, datetime

import pytest

from protean.exceptions import ValidationError
from protean.utils.reflection import attributes, declared_fields
from tests.docs.support import load_example


def test_product_declares_its_fields_and_defaults_created_at_to_now():
    example = load_example("guides/domain-definition/fields/001.py")
    example.domain.init(traverse=False)

    before = datetime.now(UTC)
    with example.domain.domain_context():
        product = example.Product(name="Pen", price=1.5)
    after = datetime.now(UTC)

    assert product.name == "Pen"
    assert product.price == 1.5
    assert before <= product.created_at <= after


def test_product_rejects_a_negative_price():
    example = load_example("guides/domain-definition/fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Product(name="Pen", price=-1)

    assert "price" in exc.value.messages


def test_order_uses_a_simple_a_container_and_an_association_field():
    example = load_example("guides/domain-definition/fields/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(customer_name="Jane Doe", tags=["gift"])
        order.add_items(example.LineItem(product_name="Pen", quantity=2, price=1.5))

    assert isinstance(order.placed_at, datetime)
    assert order.tags == ["gift"]
    assert len(order.items) == 1
    assert order.items[0].product_name == "Pen"
    assert order.items[0].order_id == order.id


def test_customer_without_an_email_is_rejected():
    example = load_example("guides/domain-definition/fields/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Customer(name="Jane Doe")

    assert exc.value.messages == {"email": ["is required"]}


def test_customer_with_an_email_is_accepted():
    example = load_example("guides/domain-definition/fields/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        customer = example.Customer(email="jane@example.com")

    assert customer.email == "jane@example.com"
    assert customer.name is None


def test_shopping_cart_fills_in_its_defaults():
    example = load_example("guides/domain-definition/fields/004.py")
    example.domain.init(traverse=False)

    before = datetime.now(UTC)
    with example.domain.domain_context():
        cart = example.ShoppingCart()
    after = datetime.now(UTC)

    assert cart.currency == "USD"
    assert before <= cart.created_at <= after


def test_listing_accepts_values_inside_its_constraints():
    example = load_example("guides/domain-definition/fields/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        listing = example.Listing(
            title="Bike", priority=5, discount=0.25, status="PUBLISHED"
        )

    assert listing.title == "Bike"
    assert listing.priority == 5
    assert listing.discount == 0.25
    assert listing.status == "PUBLISHED"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "ab"),
        ("title", "x" * 201),
        ("priority", 0),
        ("priority", 6),
        ("discount", 1.5),
        ("status", "ARCHIVED"),
    ],
)
def test_listing_rejects_values_outside_its_constraints(field, value):
    example = load_example("guides/domain-definition/fields/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Listing(**{field: value})

    assert field in exc.value.messages


def test_user_email_must_be_unique_when_saved():
    example = load_example("guides/domain-definition/fields/006.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.User)
        repo.add(example.User(email="jane@example.com", name="Jane"))

        with pytest.raises(ValidationError) as exc:
            repo.add(example.User(email="jane@example.com", name="Other Jane"))

    assert "email" in exc.value.messages


def test_employee_accepts_an_email_in_the_allowed_domain():
    example = load_example("guides/domain-definition/fields/007.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        employee = example.Employee(email="jane@mydomain.com")
        unset = example.Employee()

    assert employee.email == "jane@mydomain.com"
    # An empty value skips the validators.
    assert unset.email is None


def test_employee_rejects_an_email_in_another_domain():
    example = load_example("guides/domain-definition/fields/007.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Employee(email="jane@other.com")

    assert exc.value.messages == {"email": ["Email does not belong to mydomain.com"]}


def test_post_owns_its_comments():
    example = load_example("guides/domain-definition/fields/008.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        post = example.Post(title="Hello")
        post.add_comments(example.Comment(content="Nice post"))

    assert list(declared_fields(example.Post)) == ["title", "id", "comments"]
    assert len(post.comments) == 1
    assert post.comments[0].content == "Nice post"
    # The Reference back to Post adds a post_id shadow field on Comment.
    assert "post_id" in attributes(example.Comment)
    assert post.comments[0].post_id == post.id


def test_account_accepts_a_money_instance_or_the_flattened_attributes():
    example = load_example("guides/domain-definition/fields/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        money = example.Money(currency="USD", amount=10.0)
        from_instance = example.Account(owner="Jane", balance=money)
        from_attributes = example.Account(
            owner="Jane", balance_currency="USD", balance_amount=10.0
        )

    assert from_instance.balance == money
    assert from_attributes.balance == money


def test_money_rejects_a_negative_amount():
    example = load_example("guides/domain-definition/fields/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Money(currency="USD", amount=-1.0)

    assert "amount" in exc.value.messages


def test_person_name_is_persisted_as_full_name():
    example = load_example("guides/domain-definition/fields/010.py")
    example.domain.init(traverse=False)

    assert "full_name" in attributes(example.Person)
    assert "name" not in attributes(example.Person)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Person)
        person = example.Person(name="Jane Doe", email="jane@example.com")
        repo.add(person)
        loaded = repo.get(person.id)

    assert loaded.name == "Jane Doe"
