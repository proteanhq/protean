"""The examples on the simple fields reference behave as the page says."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from protean.exceptions import ValidationError
from protean.fields import Identifier
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example


def test_string_name_accepts_a_valid_length_and_rejects_out_of_bounds():
    example = load_example("guides/domain-definition/fields/simple-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        person = example.Person(name="John Doe")
        with pytest.raises(ValidationError) as short:
            example.Person(name="J")
        with pytest.raises(ValidationError) as long:
            example.Person(name="x" * 51)
        with pytest.raises(ValidationError) as missing:
            example.Person()

    assert person.name == "John Doe"
    assert "name" in short.value.messages
    assert "name" in long.value.messages
    assert missing.value.messages == {"name": ["is required"]}


def test_string_name_is_sanitized_because_the_example_opts_in():
    example = load_example("guides/domain-definition/fields/simple-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        person = example.Person(name="Tom & Jerry")

    assert person.name == "Tom &amp; Jerry"


def test_person_gets_an_auto_id_by_default():
    example = load_example("guides/domain-definition/fields/simple-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        person = example.Person(name="John Doe")

    assert list(declared_fields(example.Person)) == ["name", "id"]
    assert declared_fields(example.Person)["id"].identifier is True
    assert person.id


def test_text_content_is_required():
    example = load_example("guides/domain-definition/fields/simple-fields/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        book = example.Book(title="Dune", content="A long story. " * 100)
        with pytest.raises(ValidationError) as exc:
            example.Book(title="Dune")

    assert len(book.content) == 1400
    assert exc.value.messages == {"content": ["is required"]}


def test_integer_age_accepts_a_number_and_rejects_text():
    example = load_example("guides/domain-definition/fields/simple-fields/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        person = example.Person(name="John", age=42)
        with pytest.raises(ValidationError) as exc:
            example.Person(name="John", age="abc")

    assert person.age == 42
    assert "age" in exc.value.messages


def test_float_balance_defaults_to_zero_and_rejects_text():
    example = load_example("guides/domain-definition/fields/simple-fields/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        account = example.Account(name="Savings")
        with pytest.raises(ValidationError) as exc:
            example.Account(name="Savings", balance="abc")

    assert account.balance == 0.0
    assert "balance" in exc.value.messages


def test_decimal_price_keeps_exact_digits_and_rejects_bad_values():
    example = load_example("guides/domain-definition/fields/simple-fields/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        product = example.Product(price="19.99")
        with pytest.raises(ValidationError) as negative:
            example.Product(price="-1")
        with pytest.raises(ValidationError) as too_precise:
            example.Product(price="1.23456")

    assert product.price == Decimal("19.99")
    assert product.to_dict()["price"] == "19.99"
    assert "price" in negative.value.messages
    assert "price" in too_precise.value.messages


def test_date_defaults_to_today_parses_strings_and_rejects_bad_dates():
    example = load_example("guides/domain-definition/fields/simple-fields/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        today_post = example.Post(title="It")
        post = example.Post(title="Foo", published_on="2020-01-01")
        with pytest.raises(ValidationError) as exc:
            example.Post(title="Foo", published_on="2019-02-29")

    assert isinstance(today_post.published_on, date)
    assert post.published_on == date(2020, 1, 1)
    assert post.to_dict()["published_on"] == "2020-01-01"
    assert "published_on" in exc.value.messages


def test_datetime_defaults_to_an_aware_now_and_rejects_text():
    example = load_example("guides/domain-definition/fields/simple-fields/006.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        post = example.Post(title="It")
        with pytest.raises(ValidationError) as exc:
            example.Post(title="It", created_at="not a time")

    assert isinstance(post.created_at, datetime)
    assert post.created_at.tzinfo is not None
    assert "created_at" in exc.value.messages


def test_auto_now_fields_are_stamped_on_save():
    example = load_example("guides/domain-definition/fields/simple-fields/010.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        article = example.Article(title="Draft")
        assert article.created_at is None
        assert article.updated_at is None

        repo = example.domain.repository_for(example.Article)
        repo.add(article)
        saved = repo.get(article.id)
        assert saved.created_at is not None
        assert saved.updated_at is not None
        first_created, first_updated = saved.created_at, saved.updated_at

        saved.title = "Final"
        repo.add(saved)
        updated = repo.get(article.id)

    assert updated.title == "Final"
    assert updated.created_at == first_created
    assert updated.updated_at > first_updated


def test_boolean_subscribed_defaults_to_false_and_rejects_text():
    example = load_example("guides/domain-definition/fields/simple-fields/007.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(name="John Doe")
        with pytest.raises(ValidationError) as exc:
            example.User(name="John Doe", subscribed="maybe")

    assert user.subscribed is False
    assert "subscribed" in exc.value.messages


def test_identifier_user_id_is_the_identity():
    example = load_example("guides/domain-definition/fields/simple-fields/008.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(user_id=1, name="John Doe")

    assert declared_fields(example.User)["user_id"].identifier is True
    assert "id" not in declared_fields(example.User)
    assert user.subscribed is False


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Identifier always stores a string; the identity_type config does "
    "not change the field's type.",
)
def test_integer_identity_type_keeps_user_id_an_integer():
    example = load_example("guides/domain-definition/fields/simple-fields/008.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(user_id=1, name="John Doe")

    assert user.to_dict()["user_id"] == 1


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason="Identifier takes no identity_type argument.",
)
def test_identifier_rejects_an_unsupported_identity_type():
    with pytest.raises(ValidationError):
        Identifier(identity_type="foo")


def test_status_defaults_to_draft_and_rejects_an_unknown_value():
    example = load_example("guides/domain-definition/fields/simple-fields/011.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order()
        order.status = "SHIPPED"  # no transitions, so any listed value is fine
        with pytest.raises(ValidationError) as exc:
            order.status = "LOST"
        fresh = example.Order()

    assert fresh.status == "DRAFT"
    assert order.status == "SHIPPED"
    assert "status" in exc.value.messages


def test_status_transitions_allow_listed_moves_and_reject_others():
    example = load_example("guides/domain-definition/fields/simple-fields/012.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order()
        order.status = "PLACED"
        with pytest.raises(ValidationError) as exc:
            order.status = "SHIPPED"
        order.status = "CANCELLED"
        with pytest.raises(ValidationError) as terminal:
            order.status = "DRAFT"

    assert exc.value.messages == {
        "status": [
            (
                "Invalid status transition from 'PLACED' to 'SHIPPED'. "
                "Allowed transitions: CONFIRMED, CANCELLED"
            )
        ]
    }
    assert "status" in terminal.value.messages


def test_can_transition_to_reports_without_raising():
    example = load_example("guides/domain-definition/fields/simple-fields/012.py")

    assert example.order.status == "PLACED"
    assert (
        example.order.can_transition_to("status", example.OrderStatus.SHIPPED) is False
    )
    assert (
        example.order.can_transition_to("status", example.OrderStatus.CONFIRMED) is True
    )
