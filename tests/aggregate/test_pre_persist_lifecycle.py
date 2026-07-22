"""Save-path tests for lifecycle/audit support.

Covers the two mechanisms that fire in ``BaseDAO.save``:

- **Part A** — ``auto_now`` / ``auto_now_add`` timestamp stamping.
- **Part B** — registered aggregate pre-persist enrichers that stamp
  cross-cutting audit fields (``created_by`` / ``updated_by``) from ``g``.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import Date, DateTime, HasMany, String
from protean.utils.globals import g
from tests.shared import FrozenClock

_SENTINEL = datetime(2000, 1, 1, tzinfo=UTC)


class Comment(BaseEntity):
    body: String(max_length=100)


class Post(BaseAggregate):
    title: String(max_length=50)
    created_at: DateTime(auto_now_add=True)
    updated_at: DateTime(auto_now=True)
    on_date: Date(auto_now=True)  # a Date (not DateTime) auto_now field
    plain_ts: DateTime()  # a plain temporal field — must never be stamped
    created_by: String(max_length=50)
    updated_by: String(max_length=50)
    comments = HasMany(Comment)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Part A — auto_now / auto_now_add stamping
# ---------------------------------------------------------------------------
class TestAutoNowStamping:
    def test_both_flags_are_stamped_on_create(self, test_domain):
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        got = repo.get(post.id)
        assert got.created_at is not None
        assert got.updated_at is not None
        assert got.created_at.year >= 2026 and got.updated_at.year >= 2026

    def test_auto_now_refreshes_on_update_but_auto_now_add_is_frozen(self, test_domain):
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        # Freeze both timestamps to a sentinel, then trigger an update. On save,
        # auto_now (updated_at) must overwrite the sentinel with the current
        # time; auto_now_add (created_at) must leave it untouched.
        stored = repo.get(post.id)
        stored.created_at = _SENTINEL
        stored.updated_at = _SENTINEL
        stored.title = "hello again"
        repo.add(stored)

        got = repo.get(post.id)
        assert got.created_at == _SENTINEL  # auto_now_add: not refreshed on update
        assert got.updated_at.year >= 2026  # auto_now: refreshed on update

    def test_a_plain_temporal_field_is_never_stamped(self, test_domain):
        # Only auto_now/auto_now_add fields are touched; a plain DateTime stays
        # exactly as constructed (None here).
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        got = repo.get(post.id)
        assert got.plain_ts is None

    def test_auto_now_on_a_date_field_is_stamped_as_a_date(self, test_domain):
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        got = repo.get(post.id)
        assert got.on_date is not None
        assert isinstance(got.on_date, date)

    def test_auto_now_add_overrides_an_explicitly_supplied_value_on_create(
        self, test_domain
    ):
        # Django parity: auto_now_add stamps on create regardless of any value
        # the caller supplied. Use ``default=`` instead when you want to keep a
        # construction-time value.
        repo = test_domain.repository_for(Post)
        post = Post(title="hello", created_at=_SENTINEL)
        repo.add(post)

        got = repo.get(post.id)
        assert got.created_at != _SENTINEL
        assert got.created_at.year >= 2026

    def test_stamps_read_the_domain_injectable_clock(self, test_domain):
        # auto_now* uses the same clock as field defaults, so a frozen clock
        # makes the stamps deterministic (and moving it forward is observable).
        t0 = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)

        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        got = repo.get(post.id)
        assert got.created_at == t0
        assert got.updated_at == t0

        test_domain.clock.advance(timedelta(hours=3))
        stored = repo.get(post.id)
        stored.title = "hello again"
        repo.add(stored)

        got = repo.get(post.id)
        assert got.created_at == t0  # auto_now_add: pinned to the create instant
        assert got.updated_at == t0 + timedelta(hours=3)  # auto_now: advanced


# ---------------------------------------------------------------------------
# Part B — aggregate pre-persist enricher registration
# ---------------------------------------------------------------------------
class TestAggregateEnricherRegistration:
    def test_register_via_method(self, test_domain):
        calls = []
        test_domain.register_aggregate_enricher(lambda a: calls.append(a))

        test_domain.repository_for(Post).add(Post(title="x"))

        assert len(calls) == 1

    def test_register_via_decorator(self, test_domain):
        calls = []

        @test_domain.aggregate_enricher
        def record(aggregate):
            calls.append(aggregate)

        test_domain.repository_for(Post).add(Post(title="x"))

        assert len(calls) == 1

    def test_non_callable_is_rejected(self, test_domain):
        with pytest.raises(IncorrectUsageError):
            test_domain.register_aggregate_enricher("not-callable")

    def test_enrichers_run_in_registration_order(self, test_domain):
        order = []
        test_domain.register_aggregate_enricher(lambda a: order.append("first"))
        test_domain.register_aggregate_enricher(lambda a: order.append("second"))

        test_domain.repository_for(Post).add(Post(title="x"))

        assert order == ["first", "second"]

    def test_enricher_return_value_is_ignored(self, test_domain):
        # Unlike event/command enrichers (which merge a returned dict into
        # metadata.extensions), an aggregate enricher mutates in place and its
        # return value is discarded.
        @test_domain.aggregate_enricher
        def returns_a_dict(aggregate):
            aggregate.updated_by = "stamped"
            return {"updated_by": "from-return", "bogus": "x"}

        repo = test_domain.repository_for(Post)
        post = Post(title="x")
        repo.add(post)

        got = repo.get(post.id)
        assert got.updated_by == "stamped"  # the mutation, not the returned dict
        assert not hasattr(got, "bogus")  # returned keys are not applied


# ---------------------------------------------------------------------------
# Part B — aggregate pre-persist enricher behavior (the audit case)
# ---------------------------------------------------------------------------
class TestAggregateEnricherAuditStamping:
    @staticmethod
    def _register_audit_enricher(domain):
        @domain.aggregate_enricher
        def stamp_audit(aggregate):
            user = g.get("current_user")
            aggregate.updated_by = user
            if aggregate.created_by is None:
                aggregate.created_by = user

    def test_audit_fields_stamped_on_create(self, test_domain):
        self._register_audit_enricher(test_domain)

        with test_domain.domain_context(current_user="alice"):
            repo = test_domain.repository_for(Post)
            post = Post(title="x")
            repo.add(post)

            got = repo.get(post.id)
            assert got.created_by == "alice"
            assert got.updated_by == "alice"

    def test_created_by_preserved_and_updated_by_refreshed_on_update(self, test_domain):
        self._register_audit_enricher(test_domain)

        with test_domain.domain_context(current_user="alice"):
            repo = test_domain.repository_for(Post)
            post = Post(title="x")
            repo.add(post)
            post_id = post.id

        with test_domain.domain_context(current_user="bob"):
            repo = test_domain.repository_for(Post)
            stored = repo.get(post_id)
            stored.title = "y"
            repo.add(stored)

            got = repo.get(post_id)
            assert got.created_by == "alice"  # set once, preserved
            assert got.updated_by == "bob"  # refreshed every save

    def test_enricher_is_not_called_for_child_entities(self, test_domain):
        # The enricher is aggregate-scoped: a HasMany child persisted through
        # the same save path must NOT be handed to it.
        received = []
        test_domain.register_aggregate_enricher(
            lambda a: received.append(type(a).__name__)
        )

        post = Post(title="x")
        post.add_comments(Comment(body="c1"))
        post.add_comments(Comment(body="c2"))
        test_domain.repository_for(Post).add(post)

        assert len(received) > 0
        assert set(received) == {"Post"}  # never "Comment"


# ---------------------------------------------------------------------------
# Part B — negative paths
# ---------------------------------------------------------------------------
class TestAggregateEnricherNegativePaths:
    def test_save_is_clean_when_no_enricher_registered(self, test_domain):
        # auto_now still works; audit fields stay unset without an enricher.
        repo = test_domain.repository_for(Post)
        post = Post(title="x")
        repo.add(post)

        got = repo.get(post.id)
        assert got.created_at is not None  # Part A is independent of Part B
        assert got.created_by is None
        assert got.updated_by is None

    def test_enricher_exception_aborts_update_and_rolls_back_version(self, test_domain):
        repo = test_domain.repository_for(Post)
        post = Post(title="x")
        repo.add(post)  # clean create, no enricher yet

        @test_domain.aggregate_enricher
        def boom(aggregate):
            raise RuntimeError("enricher failed")

        stored = repo.get(post.id)
        version_before = stored._version
        stored.title = "y"
        with pytest.raises(RuntimeError, match="enricher failed"):
            repo.add(stored)

        # The version advance is rolled back so the entity stays consistent
        # with the store after the failed save.
        assert stored._version == version_before
