"""The examples on the common field arguments reference behave as the page says."""

from datetime import datetime

import pytest

from protean.exceptions import ValidationError
from protean.utils.eventing import Message
from protean.utils.reflection import attributes, declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_required_name_rejects_a_missing_value():
    example = load_example("guides/domain-definition/fields/options/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        person = example.Person(name="John Doe")
        with pytest.raises(ValidationError) as exc:
            example.Person()

    assert person.name == "John Doe"
    assert exc.value.messages == {"name": ["is required"]}


def test_identifier_email_is_the_identity_and_is_required():
    example = load_example("guides/domain-definition/fields/options/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        person = example.Person(email="john.doe@example.com", name="John Doe")
        with pytest.raises(ValidationError) as exc:
            example.Person(name="John Doe")

    assert declared_fields(person)["email"].identifier is True
    assert "id" not in declared_fields(person)
    assert exc.value.messages == {"email": ["is required"]}


def test_callable_default_fills_in_created_at():
    example = load_example("guides/domain-definition/fields/options/003.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context():
        post = example.Post(title="Foo")

    assert isinstance(post.created_at, datetime)
    assert post.created_at.tzinfo is not None
    assert post.to_dict()["title"] == "Foo"


def test_list_default_gives_each_adult_its_own_list():
    example = load_example("guides/domain-definition/fields/options/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        first = example.Adult(name="John Doe")
        second = example.Adult(name="Jane Doe")

    assert first.topics == ["Music", "Cinema", "Politics"]
    first.topics.append("Sports")
    assert second.topics == ["Music", "Cinema", "Politics"]


def test_lambda_default_picks_one_of_the_dice_sides():
    example = load_example("guides/domain-definition/fields/options/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        dice = example.Dice()

    assert dice.sides in [4, 6, 8, 10, 12, 20]
    assert 1 <= dice.throw() <= dice.sides


def test_unique_email_rejects_a_second_person_with_the_same_email():
    example = load_example("guides/domain-definition/fields/options/006.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Person)
        repo.add(example.Person(name="John Doe", email="john.doe@example.com"))
        with pytest.raises(ValidationError) as exc:
            repo.add(example.Person(name="Jane Doe", email="john.doe@example.com"))

    assert declared_fields(example.Person)["email"].unique is True
    assert exc.value.messages == {
        "email": ["Person with email 'john.doe@example.com' is already present."]
    }


def test_choices_accept_a_listed_status_and_reject_another():
    example = load_example("guides/domain-definition/fields/options/007.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        building = example.Building(name="Atlantis", floors=3, status="WIP")
        with pytest.raises(ValidationError) as exc:
            building.status = "COMPLETED"

    assert building.status == "WIP"
    assert exc.value.messages == {"status": ["Input should be 'WIP' or 'DONE'"]}


def test_referenced_as_stores_name_under_fullname():
    example = load_example("guides/domain-definition/fields/options/008.py")

    assert list(declared_fields(example.Person)) == ["email", "name", "id"]
    assert list(attributes(example.Person)) == ["email", "fullname", "id", "_version"]
    assert declared_fields(example.Person)["name"].referenced_as == "fullname"


def test_description_is_kept_on_the_permit_field():
    example = load_example("guides/domain-definition/fields/options/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        building = example.Building(permit=["Fire safety"])
        with pytest.raises(ValidationError) as exc:
            example.Building()

    assert declared_fields(example.Building)["permit"].description == (
        "Licences and Approvals"
    )
    assert building.permit == ["Fire safety"]
    assert "permit" in exc.value.messages


def test_custom_validator_accepts_mydomain_and_rejects_other_domains():
    example = load_example("guides/domain-definition/fields/options/010.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        employee = example.Employee(email="john@mydomain.com")
        with pytest.raises(ValidationError) as exc:
            example.Employee(email="john@otherdomain.com")

    assert employee.to_dict() == {"email": "john@mydomain.com", "_version": -1}
    assert exc.value.messages == {"email": ["Email does not belong to mydomain.com"]}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Protean ignores error_messages on a FieldSpec field and reports "
    "'is required' instead of the custom message.",
)
def test_custom_required_message_replaces_the_default():
    example = load_example("guides/domain-definition/fields/options/011.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Building()

    assert exc.value.messages == {"doors": ["Every building needs some!"]}


def _stored_order_placed(event_type: str, data: dict) -> dict:
    return {
        "data": data,
        "metadata": {
            "headers": {
                "id": "m1",
                "type": event_type,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": "ordering::order-o1",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": "OrderPlaced",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": "ordering::order",
                "version": 1,
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }


def test_renamed_from_loads_old_keys_into_the_renamed_fields():
    example = load_example("guides/domain-definition/fields/options/012.py")
    example.domain.init(traverse=False)
    stored = _stored_order_placed(
        example.OrderPlaced.__type__, {"order_id": "o1", "name": "Alice", "sum": 3.0}
    )

    with example.domain.domain_context():
        event = Message.deserialize(stored, validate=False).to_domain_object()

    assert isinstance(event, example.OrderPlaced)
    assert event.customer_name == "Alice"
    assert event.total == 3.0


def test_renamed_from_prefers_the_current_name_when_both_are_present():
    example = load_example("guides/domain-definition/fields/options/012.py")
    example.domain.init(traverse=False)
    stored = _stored_order_placed(
        example.OrderPlaced.__type__,
        {"order_id": "o1", "name": "Alice", "customer_name": "Bob", "amount": 2.0},
    )

    with example.domain.domain_context():
        event = Message.deserialize(stored, validate=False).to_domain_object()

    assert event.customer_name == "Bob"
    assert event.total == 2.0
    assert "name" not in event.to_dict()


def test_renamed_from_is_emitted_into_the_ir():
    example = load_example("guides/domain-definition/fields/options/012.py")
    example.domain.init(traverse=False)

    ir = example.domain.to_ir()
    clusters = list(ir["clusters"].values())
    assert len(clusters) == 1
    events = list(clusters[0]["events"].values())
    assert len(events) == 1

    assert events[0]["fields"]["customer_name"]["renamed_from"] == ["name"]
    assert events[0]["fields"]["total"]["renamed_from"] == ["amount", "sum"]
