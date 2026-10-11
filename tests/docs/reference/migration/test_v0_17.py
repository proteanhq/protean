"""Check what docs/reference/migration/v0-17.md says about upgrading to 0.17.

Each test loads the after-code of one migration section fresh, so every test
gets its own domain and its own memory stores. Where the page says code that
used to work now raises, a test builds that code and checks the error.
"""

import pytest

from protean import Domain
from protean._deprecation import RemovedInProtean10Warning
from protean.exceptions import (
    ConfigurationError,
    ObjectNotFoundError,
    TransactionError,
    ValidationError,
)
from protean.fields import String
from protean.utils.globals import current_uow
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def activated(domain):
    domain.init(traverse=False)
    return domain.domain_context()


def test_a_failed_nested_unit_of_work_dooms_the_outer_one():
    example = load_example("reference/migration/v0-17/001.py")

    with activated(example.domain):
        order = example.Order(customer="Jane")
        entry = example.Audit(note="order placed")

        example.place_order(order, entry)

        with pytest.raises(ObjectNotFoundError):
            example.domain.repository_for(example.Order).get(order.id)
        with pytest.raises(ObjectNotFoundError):
            example.domain.repository_for(example.Audit).get(entry.id)


def test_the_order_is_committed_before_the_partner_call(monkeypatch):
    example = load_example("reference/migration/v0-17/001.py")
    calls = []

    def record_post(url, json):
        # A UnitOfWork still open here would hold its locks during the call.
        assert not current_uow
        stored = example.domain.repository_for(example.Order).get(json["order_id"])
        calls.append((url, json, stored.status))

    with activated(example.domain):
        order = example.Order(customer="Jane")
        example.domain.repository_for(example.Order).add(order)
        monkeypatch.setattr(example.httpx, "post", record_post)

        example.confirm_order(order.id, {"order_id": order.id})

    assert calls == [
        ("https://partner.example/webhook", {"order_id": order.id}, "confirmed")
    ]


def test_get_ttl_returns_seconds():
    example = load_example("reference/migration/v0-17/008.py")

    with activated(example.domain):
        cache = example.domain.cache_for(example.UserProfile)
        cache.add(example.UserProfile(user_id="u1", name="Ada"), ttl=120)

        assert 119 < example.seconds_left(cache, "user_profile:::u1") <= 120


def test_event_sourced_marks_the_aggregate_event_sourced():
    example = load_example("reference/migration/v0-17/002.py")

    assert example.Account.meta_.is_event_sourced is True


def test_is_event_sourced_still_works_behind_a_deprecation_warning():
    domain = Domain(name="Banking")

    with pytest.warns(RemovedInProtean10Warning, match="is_event_sourced"):

        @domain.aggregate(is_event_sourced=True)
        class Account: ...

    assert Account.meta_.is_event_sourced is True


def test_event_sourced_wins_when_both_spellings_are_given():
    domain = Domain(name="Banking")

    with pytest.warns(RemovedInProtean10Warning, match="is_event_sourced"):

        @domain.aggregate(event_sourced=False, is_event_sourced=True)
        class Account: ...

    assert Account.meta_.is_event_sourced is False


def test_passing_is_fact_event_raises_configuration_error():
    domain = Domain(name="Ordering")

    @domain.aggregate
    class Order:
        customer = String()

    with pytest.raises(
        ConfigurationError,
        match="`is_fact_event` are set by the framework and cannot be provided",
    ):

        @domain.event(part_of=Order, is_fact_event=True)
        class OrderPlaced:
            customer = String()


def test_the_event_handler_calls_the_application_notification_service():
    example = load_example("reference/migration/v0-17/003.py")

    with activated(example.domain):
        person = example.Person(first_name="Jane", email="jane@example.com")
        person.raise_(example.PersonAdded(first_name="Jane", email="jane@example.com"))
        example.domain.repository_for(example.Person).add(person)

    assert example.notifications.welcomed == [("jane@example.com", "Jane")]


def test_a_sanitizing_string_checks_the_length_after_escaping():
    domain = Domain(name="Notes")

    @domain.value_object
    class Note:
        body = String(max_length=10, sanitize=True)

    with pytest.raises(ValidationError) as exc_info:
        Note(body="a & b & c")

    assert exc_info.value.messages == {
        "body": [
            "String has 17 characters after sanitization, exceeding max_length of 10"
        ]
    }


def test_an_unsanitized_string_keeps_the_text_and_checks_its_raw_length():
    example = load_example("reference/migration/v0-17/004.py")

    assert example.Note(body="a & b & c").body == "a & b & c"
    # 64 ampersands would be 320 characters once escaped.
    assert example.Note(body="&" * 64).body == "&" * 64


def test_an_application_service_takes_constructor_arguments():
    example = load_example("reference/migration/v0-17/005.py")

    with activated(example.domain):
        example.service.run("ord-1")

    assert isinstance(example.service.gateway, example.FakeGateway)
    assert example.service.gateway.charged == ["ord-1"]


def test_a_use_case_outside_a_domain_context_names_the_use_case():
    example = load_example("reference/migration/v0-17/005.py")
    example.domain.init(traverse=False)

    with pytest.raises(
        ConfigurationError,
        match=r"Use case `PlaceOrder.run` needs an active domain context.*"
        r"with domain.domain_context\(\):",
    ):
        example.service.run("ord-1")

    assert example.service.gateway.charged == []


def test_a_failing_handler_method_does_not_skip_its_sibling():
    example = load_example("reference/migration/v0-17/006.py")
    example.stock.available = False

    with activated(example.domain):
        event = example.OrderPlaced(order_id="ord-1")
        # A single failure propagates unchanged.
        with pytest.raises(example.OutOfStock, match="ord-1"):
            example.OrderReactions._handle(event)

    assert example.partner.notified == ["ord-1"]


def test_two_failing_handler_methods_are_raised_together():
    example = load_example("reference/migration/v0-17/006.py")
    example.stock.available = False
    example.partner.available = False

    with activated(example.domain):
        with pytest.raises(ExceptionGroup) as exc_info:
            example.OrderReactions._handle(example.OrderPlaced(order_id="ord-1"))

    assert sorted(type(exc).__name__ for exc in exc_info.value.exceptions) == [
        "OutOfStock",
        "PartnerDown",
    ]


def test_a_failing_handler_class_does_not_skip_its_sibling_under_sync():
    example = load_example("reference/migration/v0-17/007.py")
    example.stock.available = False

    with activated(example.domain):
        order = example.Order.place("Jane")
        with pytest.raises(TransactionError) as exc_info:
            example.domain.repository_for(example.Order).add(order)

    assert isinstance(exc_info.value.__cause__, example.OutOfStock)
    assert example.partner.notified == [order.id]


def test_two_failing_handler_classes_surface_as_a_grouped_cause():
    example = load_example("reference/migration/v0-17/007.py")
    example.stock.available = False
    example.partner.available = False

    with activated(example.domain):
        order = example.Order.place("Jane")
        with pytest.raises(TransactionError) as exc_info:
            example.domain.repository_for(example.Order).add(order)

    cause = exc_info.value.__cause__
    assert isinstance(cause, ExceptionGroup)
    assert sorted(type(exc).__name__ for exc in cause.exceptions) == [
        "OutOfStock",
        "PartnerDown",
    ]
