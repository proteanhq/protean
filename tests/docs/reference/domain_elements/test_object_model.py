"""The example on the object model reference behaves as the page says."""

import pytest

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import reflection
from tests.docs.support import load_example


def test_meta_holds_the_options_passed_to_the_decorator():
    example = load_example("guides/compose-a-domain/021.py")
    example.domain.init(traverse=False)

    meta = example.User.meta_
    assert meta.stream_category == "accounts::account"
    assert meta.aggregate_cluster is example.User


def test_meta_holds_the_defaults_for_options_not_passed():
    example = load_example("guides/compose-a-domain/021.py")
    example.domain.init(traverse=False)

    assert dict(example.User.meta_) == {
        "stream_category": "accounts::account",
        "abstract": False,
        "aggregate_cluster": example.User,
        "auto_add_id_field": True,
        "fact_events": False,
        "indexes": (),
        "is_event_sourced": False,
        "database_model": None,
        "provider": "default",
        "schema_name": "user",
        "limit": 100,
        "suppress_checks": (),
        "reserved": (),
        "deprecated": None,
    }


def test_an_abstract_element_cannot_be_instantiated():
    example = load_example("guides/compose-a-domain/021.py")

    @example.domain.aggregate(abstract=True)
    class Person:
        pass

    example.domain.init(traverse=False)

    assert Person.meta_.abstract is True
    with example.domain.domain_context():
        with pytest.raises(NotSupportedError):
            Person()
        # The concrete aggregate still is.
        assert example.User(first_name="Jane").first_name == "Jane"


def test_reflection_returns_fields_in_declaration_order():
    example = load_example("guides/compose-a-domain/021.py")
    example.domain.init(traverse=False)
    user_cls = example.User

    assert reflection.has_fields(user_cls) is True
    assert list(reflection.declared_fields(user_cls)) == [
        "first_name",
        "last_name",
        "age",
        "id",
    ]
    assert list(reflection.fields(user_cls)) == [
        "first_name",
        "last_name",
        "age",
        "id",
        "_version",
    ]
    assert list(reflection.attributes(user_cls)) == [
        "first_name",
        "last_name",
        "age",
        "id",
        "_version",
    ]


def test_reflection_finds_the_identity_and_unique_fields():
    example = load_example("guides/compose-a-domain/021.py")
    example.domain.init(traverse=False)
    user_cls = example.User

    assert reflection.has_id_field(user_cls) is True
    assert reflection.id_field(user_cls).field_name == "id"
    assert list(reflection.unique_fields(user_cls)) == ["id"]
    assert reflection.has_association_fields(user_cls) is False
    assert reflection.association_fields(user_cls) == {}


def test_reflection_accepts_an_instance_as_well_as_the_class():
    example = load_example("guides/compose-a-domain/021.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(first_name="Jane", last_name="Doe", age=30)

    assert list(reflection.declared_fields(user)) == list(
        reflection.declared_fields(example.User)
    )
    assert reflection.id_field(user).field_name == "id"


def test_reflection_rejects_a_non_container_element():
    example = load_example("guides/compose-a-domain/021.py")

    @example.domain.application_service(part_of=example.User)
    class UserService:
        pass

    with pytest.raises(IncorrectUsageError):
        reflection.fields(UserService)
