"""Save-path tests for lifecycle/audit support.

Covers the two mechanisms that fire in ``BaseDAO.save``:

- **Part A** — ``auto_now`` / ``auto_now_add`` timestamp stamping.
- **Part B** — registered aggregate pre-persist enrichers that stamp
  cross-cutting audit fields (``created_by`` / ``updated_by``) from ``g``.
- **Part C** — how both hooks interact with the aggregate's invariants:
  ``@invariant.pre`` does not run on the hook writes, ``@invariant.post``
  runs once after each hook and names the hook when it fails.
"""

from datetime import UTC, date, datetime, timedelta
from enum import Enum

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate, atomic_change
from protean.core.entity import BaseEntity, invariant
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError, ValidationError
from protean.fields import Date, DateTime, HasMany, Identifier, Status, String
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


class Entry(BaseEntity):
    memo: String(max_length=50)
    updated_at: DateTime(auto_now=True)


class Account(BaseAggregate):
    status: String(default="OPEN")
    updated_at: DateTime(auto_now=True)
    entries = HasMany(Entry)

    @invariant.pre
    def closed_accounts_are_immutable(self):
        if self.status == "CLOSED":
            raise ValidationError({"_account": ["A closed account cannot be modified"]})

    def close(self):
        self.status = "CLOSED"


class Ledger(BaseAggregate):
    """``Account`` without an ``auto_now`` field, for the enricher cases."""

    status: String(default="OPEN")
    updated_by: String(max_length=50)
    reviewer: String(max_length=50)

    @invariant.pre
    def closed_ledgers_are_immutable(self):
        if self.status == "CLOSED":
            raise ValidationError({"_ledger": ["A closed ledger cannot be modified"]})

    @invariant.post
    def updater_is_not_the_reviewer(self):
        if self.updated_by is not None and self.updated_by == self.reviewer:
            raise ValidationError(
                {"_ledger": ["The updater cannot also review the ledger"]}
            )

    def close(self):
        self.status = "CLOSED"


class BatchStage(Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ARCHIVED = "ARCHIVED"


class LedgerAudited(BaseEvent):
    ledger_id: Identifier()


class Batch(BaseAggregate):
    stage: Status(
        BatchStage,
        default="DRAFT",
        transitions={"DRAFT": ["SENT"], "SENT": ["ARCHIVED"]},
    )
    note: String(max_length=50)


class Reading(BaseAggregate):
    value: String(max_length=50)
    updated_at: DateTime(auto_now=True)
    created_at: DateTime(auto_now_add=True)

    @invariant.post
    def not_stamped_in_a_maintenance_window(self):
        if self.updated_at is not None and self.updated_at.year == 2031:
            raise ValidationError({"updated_at": ["Readings are frozen in 2031"]})


class WalletOpened(BaseEvent):
    wallet_id: Identifier()


class Wallet(BaseAggregate):
    updated_by: String(max_length=50)

    @classmethod
    def open(cls) -> "Wallet":
        wallet = cls()
        wallet.raise_(WalletOpened(wallet_id=wallet.id))
        return wallet

    @apply
    def opened(self, event: WalletOpened) -> None:
        pass


class AccountSummary(BaseProjection):
    account_id: Identifier(identifier=True)
    updated_at: DateTime(auto_now=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.register(Account)
    test_domain.register(Entry, part_of=Account)
    test_domain.register(Ledger)
    test_domain.register(LedgerAudited, part_of=Ledger)
    test_domain.register(Batch)
    test_domain.register(Reading)
    test_domain.register(AccountSummary)
    test_domain.register(Wallet, is_event_sourced=True)
    test_domain.register(WalletOpened, part_of=Wallet)
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
        # Stamped to "now" — after the year-2000 sentinel, not left unset.
        assert got.created_at > _SENTINEL and got.updated_at > _SENTINEL

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
        assert got.updated_at > _SENTINEL  # auto_now: refreshed past the sentinel

    def test_auto_now_refreshes_via_the_dao_update_path(self, test_domain):
        # The DAO ``update()`` path stamps ``auto_now`` too, since it now
        # persists through ``save`` (previously it skipped lifecycle stamping).
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        stored = repo.get(post.id)
        stored.created_at = _SENTINEL
        stored.updated_at = _SENTINEL
        repo._dao.update(stored, title="hello again")

        got = repo.get(post.id)
        assert got.created_at == _SENTINEL  # auto_now_add: not refreshed on update
        assert got.updated_at > _SENTINEL  # auto_now: refreshed via update()

    def test_apply_hooks_false_skips_stamping_on_update(self, test_domain):
        # ``apply_hooks=False`` opts out of the hooks for a raw write.
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        stored = repo.get(post.id)
        stored.updated_at = _SENTINEL
        repo._dao.update(stored, title="raw", apply_hooks=False)

        got = repo.get(post.id)
        assert got.title == "raw"  # the write still happened
        assert got.updated_at == _SENTINEL  # auto_now NOT refreshed
        assert got._version == 1  # but OCC/version is still applied (not gated)

    def test_apply_hooks_false_skips_stamping_on_save(self, test_domain):
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        stored = repo.get(post.id)
        stored.updated_at = _SENTINEL
        stored.title = "raw"
        repo._dao.save(stored, apply_hooks=False)

        got = repo.get(post.id)
        assert got.title == "raw"
        assert got.updated_at == _SENTINEL  # auto_now NOT refreshed

    def test_apply_hooks_flag_threads_through_queryset_update(self, test_domain):
        # The flag reaches each row of the per-item QuerySet.update() loop.
        repo = test_domain.repository_for(Post)
        post = Post(title="hello")
        repo.add(post)

        # Seed a sentinel via a raw update (which does not re-stamp).
        stored = repo.get(post.id)
        stored.updated_at = _SENTINEL
        repo._dao.update(stored, title="seed", apply_hooks=False)
        assert repo.get(post.id).updated_at == _SENTINEL

        # Bulk update with the flag off must NOT re-stamp.
        repo._dao.query.filter(title="seed").update(title="bulk", apply_hooks=False)
        assert repo.get(post.id).updated_at == _SENTINEL

        # Control: the default bulk update DOES re-stamp — so the assertion above
        # is not vacuous.
        repo._dao.query.filter(title="bulk").update(title="bulk2")
        assert repo.get(post.id).updated_at > _SENTINEL

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
        assert got.created_at != _SENTINEL  # stamped fresh, not the supplied value

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

    def test_enricher_runs_on_the_dao_update_path(self, test_domain):
        # The DAO ``update()`` path runs pre-persist enrichers too (it persists
        # through ``save``), so audit fields are refreshed on an update() write.
        self._register_audit_enricher(test_domain)

        with test_domain.domain_context(current_user="alice"):
            repo = test_domain.repository_for(Post)
            post = Post(title="x")
            repo.add(post)
            post_id = post.id

        with test_domain.domain_context(current_user="bob"):
            repo = test_domain.repository_for(Post)
            stored = repo.get(post_id)
            repo._dao.update(stored, title="y")

            got = repo.get(post_id)
            assert got.created_by == "alice"  # preserved
            assert got.updated_by == "bob"  # refreshed via update()'s enricher run

    def test_enricher_skipped_when_apply_hooks_false(self, test_domain):
        # ``apply_hooks=False`` opts out of enrichers on the update path.
        self._register_audit_enricher(test_domain)

        with test_domain.domain_context(current_user="alice"):
            repo = test_domain.repository_for(Post)
            post = Post(title="x")
            repo.add(post)
            post_id = post.id

        with test_domain.domain_context(current_user="bob"):
            repo = test_domain.repository_for(Post)
            stored = repo.get(post_id)
            repo._dao.update(stored, title="y", apply_hooks=False)

            got = repo.get(post_id)
            assert got.title == "y"  # the write still happened
            assert got.updated_by == "alice"  # enricher did NOT run for "bob"

    def test_enricher_runs_for_each_row_of_a_queryset_update(self, test_domain):
        self._register_audit_enricher(test_domain)

        with test_domain.domain_context(current_user="alice"):
            repo = test_domain.repository_for(Post)
            repo.add(Post(title="bulk"))
            repo.add(Post(title="bulk"))

        with test_domain.domain_context(current_user="bob"):
            repo = test_domain.repository_for(Post)
            repo._dao.query.filter(title="bulk").update(title="done")

            rows = repo._dao.query.filter(title="done").all().items
            assert len(rows) == 2
            assert all(row.updated_by == "bob" for row in rows)

    def test_enricher_does_not_run_for_event_sourced_aggregates(self, test_domain):
        calls = []
        test_domain.register_aggregate_enricher(lambda a: calls.append(a))

        with UnitOfWork():
            test_domain.repository_for(Wallet).add(Wallet.open())

        # The memory event store saves its message rows through a DAO, so the
        # enricher sees those rows. It never receives the aggregate itself.
        assert not any(isinstance(a, Wallet) for a in calls)

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


# ---------------------------------------------------------------------------
# Part C — pre-persist hooks and invariants
# ---------------------------------------------------------------------------
def _closed_account(domain):
    repo = domain.repository_for(Account)
    account = Account()
    repo.add(account)
    account = repo.get(account.id)
    account.close()
    return repo, account


def _stamp_updated_by(aggregate):
    if isinstance(aggregate, Ledger):
        aggregate.updated_by = "alice"


class TestPreInvariantsDoNotRunOnHookWrites:
    def test_a_closed_aggregate_saves_with_an_auto_now_field(self, test_domain):
        t0 = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)
        repo, account = _closed_account(test_domain)
        assert account.updated_at == t0

        test_domain.clock.advance(timedelta(minutes=5))
        repo.add(account)

        got = repo.get(account.id)
        assert got.status == "CLOSED"
        assert got.updated_at == t0 + timedelta(minutes=5)

    def test_a_closed_aggregate_saves_through_dao_update(self, test_domain):
        t0 = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)
        repo = test_domain.repository_for(Account)
        account = Account()
        repo.add(account)

        test_domain.clock.advance(timedelta(minutes=5))
        stored = repo.get(account.id)
        repo._dao.update(stored, status="CLOSED")

        got = repo.get(account.id)
        assert got.status == "CLOSED"
        assert got.updated_at == t0 + timedelta(minutes=5)

    def test_a_closed_aggregate_saves_with_an_enricher(self, test_domain):
        test_domain.register_aggregate_enricher(_stamp_updated_by)
        repo = test_domain.repository_for(Ledger)
        ledger = Ledger()
        repo.add(ledger)

        ledger = repo.get(ledger.id)
        ledger.close()
        repo.add(ledger)

        got = repo.get(ledger.id)
        assert got.status == "CLOSED"
        assert got.updated_by == "alice"

    def test_a_closed_aggregate_saves_with_an_enricher_through_dao_update(
        self, test_domain
    ):
        test_domain.register_aggregate_enricher(_stamp_updated_by)
        repo = test_domain.repository_for(Ledger)
        ledger = Ledger()
        repo.add(ledger)

        repo._dao.update(repo.get(ledger.id), status="CLOSED")

        got = repo.get(ledger.id)
        assert got.status == "CLOSED"
        assert got.updated_by == "alice"

    def test_a_child_entity_stamp_does_not_run_the_root_pre_invariants(
        self, test_domain
    ):
        t0 = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)
        repo = test_domain.repository_for(Account)
        account = Account(entries=[Entry(memo="opening")])
        repo.add(account)

        # Change the child too, so the save writes it and stamps it.
        test_domain.clock.advance(timedelta(minutes=5))
        account = repo.get(account.id)
        account.entries[0].memo = "adjusted"
        account.close()
        repo.add(account)

        got = repo.get(account.id)
        assert got.status == "CLOSED"
        assert len(got.entries) == 1
        assert got.entries[0].memo == "adjusted"
        assert got.entries[0].updated_at == t0 + timedelta(minutes=5)

    def test_the_pre_invariant_still_rejects_a_business_change(self, test_domain):
        _, account = _closed_account(test_domain)

        with pytest.raises(ValidationError) as exc:
            account.status = "OPEN"

        assert exc.value.messages == {
            "_account": ["A closed account cannot be modified"]
        }

    def test_post_invariants_run_once_after_the_enricher(self, test_domain):
        # The enricher passes through a state the post-invariant rejects
        # (updater == reviewer) and leaves a valid one. Only the end state
        # is checked.
        @test_domain.aggregate_enricher
        def swap_reviewer(aggregate):
            aggregate.updated_by = "alice"
            aggregate.reviewer = "bob"

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="alice")
        repo.add(ledger)

        got = repo.get(ledger.id)
        assert (got.updated_by, got.reviewer) == ("alice", "bob")

    def test_a_business_change_inside_atomic_change_is_blamed_on_the_aggregate(
        self, test_domain
    ):
        # ``updated_by`` is already "alice" from the first save, so the
        # enricher writes nothing new. The block's own change breaks the
        # invariant, and the block's exit check reports it.
        @test_domain.aggregate_enricher
        def stamp_audit(aggregate):
            if isinstance(aggregate, Ledger):
                aggregate.updated_by = "alice"

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="bob")
        repo.add(ledger)
        ledger = repo.get(ledger.id)

        with pytest.raises(ValidationError) as exc:
            with atomic_change(ledger):
                ledger.reviewer = "alice"
                repo.add(ledger)

        assert exc.value.messages == {
            "_ledger": ["The updater cannot also review the ledger"]
        }
        assert exc.value.location == "Ledger"


class TestPostInvariantFailuresNameTheHook:
    def test_an_enricher_failure_aborts_the_update(self, test_domain):
        @test_domain.aggregate_enricher
        def stamp_audit(aggregate):
            if isinstance(aggregate, Ledger):
                aggregate.updated_by = "alice"

        repo = test_domain.repository_for(Ledger)
        # Seed the row with the hooks off, so the enricher's first run is on
        # the update.
        ledger = Ledger(reviewer="alice")
        repo._dao.save(ledger, apply_hooks=False)

        stored = repo.get(ledger.id)
        version_before = stored._version
        stored.status = "REVIEWED"

        with pytest.raises(ValidationError) as exc:
            repo.add(stored)

        assert exc.value.messages == {
            "_ledger": ["The updater cannot also review the ledger"]
        }
        assert exc.value.location is not None
        assert "stamp_audit" in exc.value.location
        assert exc.value.location.startswith("aggregate enricher ")
        assert exc.value.codes, "the invariant's diagnostic code is kept"
        assert stored._version == version_before
        assert repo.get(ledger.id).status == "OPEN"  # nothing persisted
        # The enricher's write is undone along with the failed check.
        assert stored.updated_by is None
        assert stored.status == "REVIEWED"

    def test_an_enricher_failure_aborts_the_create(self, test_domain):
        @test_domain.aggregate_enricher
        def stamp_audit(aggregate):
            if isinstance(aggregate, Ledger):
                aggregate.updated_by = "alice"

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="alice")

        with pytest.raises(ValidationError) as exc:
            repo.add(ledger)

        assert exc.value.location is not None
        assert "stamp_audit" in exc.value.location
        with pytest.raises(ObjectNotFoundError):
            repo.get(ledger.id)

    def test_an_auto_now_failure_names_the_stamping_and_the_field(self, test_domain):
        test_domain.clock = FrozenClock(datetime(2030, 6, 1, tzinfo=UTC))
        repo = test_domain.repository_for(Reading)
        reading = Reading()
        repo.add(reading)

        stored = repo.get(reading.id)
        version_before = stored._version
        test_domain.clock = FrozenClock(datetime(2031, 6, 1, tzinfo=UTC))
        stored.value = "42"

        with pytest.raises(ValidationError) as exc:
            repo.add(stored)

        assert exc.value.messages == {"updated_at": ["Readings are frozen in 2031"]}
        assert exc.value.location == "auto_now stamping of updated_at on Reading"
        assert stored._version == version_before
        assert repo.get(reading.id).updated_at.year == 2030

    def test_a_status_transition_made_by_an_enricher_is_still_checked(
        self, test_domain
    ):
        @test_domain.aggregate_enricher
        def archive(aggregate):
            if isinstance(aggregate, Batch):
                aggregate.stage = "ARCHIVED"

        repo = test_domain.repository_for(Batch)
        batch = Batch()
        repo._dao.save(batch, apply_hooks=False)
        stored = repo.get(batch.id)
        stored.note = "ready"

        with pytest.raises(ValidationError) as exc:
            repo.add(stored)

        assert exc.value.messages == {
            "stage": [
                (
                    "Invalid status transition from 'DRAFT' to 'ARCHIVED'. "
                    "Allowed transitions: SENT"
                )
            ]
        }
        assert exc.value.location is not None
        assert "archive" in exc.value.location
        assert repo.get(batch.id).stage == "DRAFT"

    def test_a_raising_enricher_keeps_its_messages_and_names_itself(self, test_domain):
        @test_domain.aggregate_enricher
        def reject(aggregate):
            raise ValidationError({"_audit": ["no actor"]})

        repo = test_domain.repository_for(Ledger)
        with pytest.raises(ValidationError) as exc:
            repo.add(Ledger())

        assert exc.value.messages == {"_audit": ["no actor"]}
        assert exc.value.location is not None
        assert "reject" in exc.value.location

    def test_a_location_the_enricher_set_is_kept(self, test_domain):
        @test_domain.aggregate_enricher
        def reject(aggregate):
            raise ValidationError({"_audit": ["no actor"]}, location="audit.actor")

        repo = test_domain.repository_for(Ledger)
        with pytest.raises(ValidationError) as exc:
            repo.add(Ledger())

        assert exc.value.location == "audit.actor"

    def test_a_crashing_enricher_is_not_hidden_by_an_invariant_failure(
        self, test_domain
    ):
        # The half-finished write breaks the post-invariant. The enricher's
        # own error is what the caller sees, and its write is undone.
        @test_domain.aggregate_enricher
        def half_done(aggregate):
            if not isinstance(aggregate, Ledger):
                return
            aggregate.updated_by = "alice"
            raise RuntimeError("actor lookup failed")

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="alice")

        with pytest.raises(RuntimeError, match="actor lookup failed"):
            repo.add(ledger)

        assert ledger.updated_by is None
        with pytest.raises(ObjectNotFoundError):
            repo.get(ledger.id)

    def test_a_save_mid_atomic_change_leaves_the_checks_to_the_block(self, test_domain):
        # updated_by == reviewer is invalid for a moment inside the block,
        # when the save runs. The block's exit check sees the final state.
        @test_domain.aggregate_enricher
        def stamp_audit(aggregate):
            if isinstance(aggregate, Ledger):
                aggregate.updated_by = "carol"

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="bob")
        repo._dao.save(ledger, apply_hooks=False)
        ledger = repo.get(ledger.id)

        with atomic_change(ledger):
            ledger.reviewer = "carol"
            repo.add(ledger)
            ledger.reviewer = "dave"

        assert (ledger.updated_by, ledger.reviewer) == ("carol", "dave")

    def test_a_raising_enricher_mid_atomic_change_is_undone(self, test_domain):
        @test_domain.aggregate_enricher
        def audit(aggregate):
            if not isinstance(aggregate, Ledger):
                return
            aggregate.updated_by = "carol"
            aggregate.raise_(LedgerAudited(ledger_id=aggregate.id))
            raise RuntimeError("audit sink down")

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="bob")
        repo._dao.save(ledger, apply_hooks=False)
        ledger = repo.get(ledger.id)

        # Left in place, updated_by == reviewer would fail the block's exit
        # check and hide the enricher's own exception.
        with pytest.raises(RuntimeError, match="audit sink down"):
            with atomic_change(ledger):
                ledger.reviewer = "carol"
                repo.add(ledger)

        assert ledger.updated_by is None
        assert ledger._events == []
        assert repo.get(ledger.id).reviewer == "bob"

    def test_an_enricher_failure_through_dao_update(self, test_domain):
        @test_domain.aggregate_enricher
        def stamp_audit(aggregate):
            if isinstance(aggregate, Ledger):
                aggregate.updated_by = "alice"

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="alice")
        repo._dao.save(ledger, apply_hooks=False)
        stored = repo.get(ledger.id)
        version_before = stored._version

        with pytest.raises(ValidationError) as exc:
            repo._dao.update(stored, status="REVIEWED")

        assert exc.value.location is not None
        assert "stamp_audit" in exc.value.location
        assert stored._version == version_before
        assert repo.get(ledger.id).status == "OPEN"

    def test_an_auto_now_failure_through_dao_update(self, test_domain):
        test_domain.clock = FrozenClock(datetime(2030, 6, 1, tzinfo=UTC))
        repo = test_domain.repository_for(Reading)
        reading = Reading()
        repo.add(reading)
        stored = repo.get(reading.id)
        test_domain.clock = FrozenClock(datetime(2031, 6, 1, tzinfo=UTC))

        with pytest.raises(ValidationError) as exc:
            repo._dao.update(stored, value="42")

        assert exc.value.location == "auto_now stamping of updated_at on Reading"
        assert repo.get(reading.id).value is None

    def test_a_failed_stamp_skips_the_enrichers(self, test_domain):
        calls = []
        test_domain.register_aggregate_enricher(lambda a: calls.append(type(a)))
        test_domain.clock = FrozenClock(datetime(2031, 6, 1, tzinfo=UTC))

        with pytest.raises(ValidationError) as exc:
            test_domain.repository_for(Reading).add(Reading())

        # On create both fields are stamped, and the location names both.
        assert exc.value.location == (
            "auto_now stamping of updated_at, created_at on Reading"
        )
        assert calls == []

    def test_the_enricher_sees_the_stamped_value(self, test_domain):
        t0 = datetime(2030, 6, 1, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)
        seen = []
        test_domain.register_aggregate_enricher(
            lambda a: seen.append(a.updated_at) if isinstance(a, Reading) else None
        )

        test_domain.repository_for(Reading).add(Reading())

        assert seen == [t0]

    def test_the_aggregate_saves_after_a_failed_hook(self, test_domain):
        @test_domain.aggregate_enricher
        def stamp_audit(aggregate):
            if isinstance(aggregate, Ledger):
                aggregate.updated_by = "alice"

        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(reviewer="alice")
        with pytest.raises(ValidationError):
            repo.add(ledger)

        ledger.reviewer = "bob"
        repo.add(ledger)

        got = repo.get(ledger.id)
        assert (got.updated_by, got.reviewer) == ("alice", "bob")

    def test_a_raising_enricher_drops_the_events_it_raised(self, test_domain):
        @test_domain.aggregate_enricher
        def audit(aggregate):
            if not isinstance(aggregate, Ledger):
                return
            aggregate.raise_(LedgerAudited(ledger_id=aggregate.id))
            raise RuntimeError("audit sink down")

        ledger = Ledger()
        with pytest.raises(RuntimeError, match="audit sink down"):
            test_domain.repository_for(Ledger).add(ledger)

        assert ledger._events == []

    def test_checks_are_back_on_after_a_raising_enricher(self, test_domain):
        @test_domain.aggregate_enricher
        def crash(aggregate):
            if not isinstance(aggregate, Ledger):
                return
            raise RuntimeError("actor lookup failed")

        ledger = Ledger(reviewer="alice")
        with pytest.raises(RuntimeError):
            test_domain.repository_for(Ledger).add(ledger)

        with pytest.raises(ValidationError):
            ledger.updated_by = "alice"


class TestPreInvariantsOnOtherSavePaths:
    def test_a_closed_aggregate_saves_inside_a_unit_of_work(self, test_domain):
        repo, account = _closed_account(test_domain)

        with UnitOfWork():
            repo.add(account)

        assert repo.get(account.id).status == "CLOSED"

    def test_a_closed_aggregate_saves_through_queryset_update(self, test_domain):
        t0 = datetime(2030, 6, 1, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)
        repo = test_domain.repository_for(Account)
        account = Account()
        repo.add(account)

        test_domain.clock.advance(timedelta(minutes=5))
        repo._dao.query.filter(id=account.id).update(status="CLOSED")

        got = repo.get(account.id)
        assert got.status == "CLOSED"
        assert got.updated_at == t0 + timedelta(minutes=5)


class TestHookWritesOnObjectsWithoutAnAggregate:
    def test_an_entity_saved_on_its_own_is_stamped(self, test_domain):
        t0 = datetime(2030, 6, 1, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)
        entry = Entry(memo="loose", account_id="a1")

        test_domain.repository_for(Entry)._dao.save(entry)

        assert entry.updated_at == t0

    def test_a_projection_is_stamped(self, test_domain):
        t0 = datetime(2030, 6, 1, tzinfo=UTC)
        test_domain.clock = FrozenClock(t0)
        summary = AccountSummary(account_id="a1")

        test_domain.repository_for(AccountSummary).add(summary)

        got = test_domain.repository_for(AccountSummary).get("a1")
        assert got.updated_at == t0
