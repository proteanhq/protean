"""Run the facet-sync example on ``docs/patterns/calling-external-systems-from-handlers.md``."""

import pytest

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
