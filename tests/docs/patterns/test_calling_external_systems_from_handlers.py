"""Run the examples on ``docs/patterns/calling-external-systems-from-handlers.md``."""

import httpx
import pytest

from protean.exceptions import TransactionError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    domain = example.domain
    domain.init(traverse=False)
    return domain.domain_context()


def _store_snapshot(example, **values):
    snapshot = example.ProfileSnapshot(subscriber_id="s1", **values)
    snapshot.store()
    example.domain.repository_for(example.ProfileSnapshot).add(snapshot)
    return snapshot


def _subscriber_repo(example):
    repo = example.domain.repository_for(example.Subscriber)
    repo.add(example.Subscriber(subscriber_id="s1"))
    return repo


def _check_codes(example):
    report = example.domain.check(traverse=False)
    return {entry["code"] for entry in report["errors"]} | {
        entry["code"] for entry in report["diagnostics"]
    }


def test_storing_a_snapshot_applies_contact_plan_and_flags():
    example = load_example("patterns/calling-external-systems-from-handlers/001.py")
    with _context(example):
        repo = _subscriber_repo(example)

        snapshot = _store_snapshot(
            example, email="ada@example.com", name="Ada", tier="team", seats=5
        )

        subscriber = repo.get("s1")
        assert (subscriber.email, subscriber.name) == ("ada@example.com", "Ada")
        assert (subscriber.tier, subscriber.seats) == ("team", 5)
        assert subscriber.flags == ["exports", "sso"]
        assert subscriber.applied_snapshot_ids == [snapshot.snapshot_id]


def test_a_repeated_snapshot_leaves_the_subscriber_unchanged():
    example = load_example("patterns/calling-external-systems-from-handlers/001.py")
    with _context(example):
        repo = _subscriber_repo(example)
        snapshot = _store_snapshot(
            example, email="ada@example.com", name="Ada", tier="pro", seats=2
        )
        before = repo.get("s1")

        example.domain.process(
            example.ApplyProfileSnapshot(
                subscriber_id="s1", snapshot_id=snapshot.snapshot_id
            )
        )

        after = repo.get("s1")
        assert after._version == before._version
        assert after.to_dict() == before.to_dict()


def test_a_new_snapshot_is_applied_after_an_earlier_one():
    example = load_example("patterns/calling-external-systems-from-handlers/001.py")
    with _context(example):
        repo = _subscriber_repo(example)
        first = _store_snapshot(
            example, email="ada@example.com", name="Ada", tier="team", seats=5
        )
        second = _store_snapshot(
            example, email="ada@new.example.com", name="Ada L", tier="free", seats=1
        )

        subscriber = repo.get("s1")
        assert subscriber.email == "ada@new.example.com"
        assert (subscriber.tier, subscriber.flags) == ("free", [])
        assert subscriber.applied_snapshot_ids == [
            first.snapshot_id,
            second.snapshot_id,
        ]


def test_the_hand_off_stays_with_the_snapshot():
    example = load_example("patterns/calling-external-systems-from-handlers/001.py")
    with _context(example):
        handler = example.ProfileSnapshotHandler
        assert handler.meta_.part_of is example.ProfileSnapshot
        assert example.ApplyProfileSnapshot.meta_.part_of is example.Subscriber
        assert example.SubscriberCommandHandler.meta_.part_of is example.Subscriber
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in _check_codes(example)


class _Partner:
    """Stands in for ``post_to_partner`` and records what the order looked like
    when the call ran."""

    def __init__(self, example, fail=False):
        self.example = example
        self.fail = fail
        self.payloads = []
        self.orders_seen = []

    def __call__(self, payload):
        self.payloads.append(payload)
        repo = self.example.domain.repository_for(self.example.Order)
        self.orders_seen.append(repo.get(payload["order_id"]).to_dict())
        if self.fail:
            raise ConnectionError("partner is down")


def _place_order(example, order_id="o1"):
    repo = example.domain.repository_for(example.Order)
    repo.add(example.Order.place(order_id))
    return repo


def test_sibling_methods_start_fulfilment_and_notify_the_partner(monkeypatch):
    example = load_example("patterns/calling-external-systems-from-handlers/002.py")
    with _context(example):
        partner = _Partner(example)
        monkeypatch.setattr(example, "post_to_partner", partner)

        repo = _place_order(example)

        assert partner.payloads == [{"order_id": "o1"}]
        assert repo.get("o1").fulfilment_status == "STARTED"


def test_a_failing_partner_call_leaves_the_sibling_write_in_place(monkeypatch):
    example = load_example("patterns/calling-external-systems-from-handlers/002.py")
    with _context(example):
        partner = _Partner(example, fail=True)
        monkeypatch.setattr(example, "post_to_partner", partner)

        with pytest.raises(TransactionError) as caught:
            _place_order(example)

        assert isinstance(caught.value.__cause__, ConnectionError)
        assert partner.payloads == [{"order_id": "o1"}]
        order = example.domain.repository_for(example.Order).get("o1")
        assert order.fulfilment_status == "STARTED"


def test_the_partner_call_sees_a_committed_confirmed_order(monkeypatch):
    example = load_example("patterns/calling-external-systems-from-handlers/003.py")
    with _context(example):
        partner = _Partner(example)
        monkeypatch.setattr(example, "post_to_partner", partner)

        repo = _place_order(example)

        order = repo.get("o1")
        assert order.status == "CONFIRMED"
        assert partner.payloads == [
            {"order_id": "o1", "confirmed_at": order.confirmed_at.isoformat()}
        ]
        assert len(partner.orders_seen) == 1
        seen = partner.orders_seen[0]
        assert seen["status"] == "CONFIRMED"
        assert seen["confirmed_at"] == order.confirmed_at.isoformat()


def test_an_unconfirmed_order_makes_no_partner_call(monkeypatch):
    example = load_example("patterns/calling-external-systems-from-handlers/003.py")
    with _context(example):
        partner = _Partner(example)
        monkeypatch.setattr(example, "post_to_partner", partner)

        repo = example.domain.repository_for(example.Order)
        repo.add(example.Order(order_id="o2"))

        assert repo.get("o2").status == "PLACED"
        assert partner.payloads == []


def test_a_failing_partner_call_does_not_undo_the_confirmation(monkeypatch):
    example = load_example("patterns/calling-external-systems-from-handlers/003.py")
    with _context(example):
        partner = _Partner(example, fail=True)
        monkeypatch.setattr(example, "post_to_partner", partner)

        # With sync processing the partner call runs after the confirming
        # commit, so its error reaches the caller once the write is durable.
        with pytest.raises(TransactionError) as caught:
            _place_order(example)

        assert isinstance(caught.value.__cause__, ConnectionError)
        assert partner.orders_seen[0]["status"] == "CONFIRMED"
        order = example.domain.repository_for(example.Order).get("o1")
        assert order.status == "CONFIRMED"
        assert order.confirmed_at is not None


def _respond_with(calls, body):
    def respond(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    return respond


def test_a_sync_request_fetches_once_and_applies_the_snapshot(monkeypatch):
    example = load_example("patterns/calling-external-systems-from-handlers/001.py")
    with _context(example):
        calls = []
        body = {
            "email": "ada@example.com",
            "name": "Ada",
            "plan": {"tier": "pro", "seats": 3},
        }
        monkeypatch.setattr(example.httpx, "get", _respond_with(calls, body))
        repo = _subscriber_repo(example)

        subscriber = repo.get("s1")
        subscriber.request_sync()
        repo.add(subscriber)

        assert calls == [("https://billing.example.com/subscribers/s1", {})]
        subscriber = repo.get("s1")
        assert (subscriber.email, subscriber.name) == ("ada@example.com", "Ada")
        assert (subscriber.tier, subscriber.seats) == ("pro", 3)
        assert subscriber.flags == ["exports"]
        assert len(subscriber.applied_snapshot_ids) == 1


def test_the_fetch_before_the_persist_is_not_flagged():
    example = load_example("patterns/calling-external-systems-from-handlers/001.py")
    with _context(example):
        assert "HANDLER_PERSISTS_AND_CALLS_OUT" not in _check_codes(example)


def test_the_validator_result_is_stored_on_the_customer(monkeypatch):
    example = load_example("patterns/calling-external-systems-from-handlers/004.py")
    with _context(example):
        calls = []
        body = {"normalized": "1 Main St, Springfield, IL 62701"}
        monkeypatch.setattr(example.httpx, "post", _respond_with(calls, body))
        repo = example.domain.repository_for(example.Customer)
        repo.add(example.Customer(customer_id="c1"))

        customer = repo.get("c1")
        customer.submit_address("1 main street springfield")
        repo.add(customer)

        assert calls == [
            (
                "https://address-validator.example.com/normalize",
                {"json": {"address": "1 main street springfield"}},
            )
        ]
        assert repo.get("c1").address == "1 Main St, Springfield, IL 62701"


def test_calling_before_the_repository_is_not_flagged():
    example = load_example("patterns/calling-external-systems-from-handlers/004.py")
    with _context(example):
        assert "HANDLER_PERSISTS_AND_CALLS_OUT" not in _check_codes(example)
