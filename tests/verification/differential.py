"""Differential adapter-parity harness (:issue:`#1270`).

The property suite in :issue:`#1251` runs randomized histories against a *single*
adapter and checks each against an oracle. The cross-adapter conformance suite
(:issue:`#950`) runs *fixed* tests against every adapter. Neither runs *the same
randomized history against two adapters and diffs the outcomes* — and that
intersection is exactly where an adapter-specific divergence hides. :issue:`#1087`
(the OCC lost-update) was one: the Memory adapter's behavior diverged from
SQLAlchemy's under a stale-version write, and a single-adapter test could not see
it.

This harness closes that gap. It:

* generates a randomized history of repository operations (``add``, ``update``,
  a sequential concurrent-update, ``read``, filtered ``query``, ``delete``) over
  a small pool of aggregates (:func:`histories`);
* replays the **identical** history against two adapters and records the
  observable outcome of every step (:func:`run_history`) — final aggregate
  state, ``_version``, query result sets, and the *class* of any raised
  exception;
* diffs the two observation lists (:func:`diff_observations`); any divergence is
  a failing test that Hypothesis shrinks to a minimal reproduction.

Covers the same adapters as the ``transactional`` conformance tier (Memory + SQL);
the Event Store is excluded because ``F()`` / OCC semantics legitimately differ
there (the tiering :issue:`#950` established). The core suite diffs Memory against
SQLite (no Docker); the FULL leg diffs Memory against PostgreSQL.

A differential harness can only catch behavior where the two adapters *disagree*;
a bug both share would pass unseen. Two planted-bug seeds guard against a vacuous
pass by making a real divergence on each observation channel and proving it is
caught: ``lost_update`` (the concurrency / exception channel) and
``dropped_balance`` (the read / query / final-state channels).

The observation format is deliberately plain (tuples of primitives) so a
divergence prints as a readable, shrunk counterexample rather than an object
graph.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

from hypothesis import settings
from hypothesis import strategies as st

from protean.adapters.repository.memory import DictDAO, MemoryProvider
from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository
from protean.domain import Domain
from protean.fields import Integer, String
from tests.verification.strategies import _names, property_settings

# A single observation (one operation's outcome, or the final snapshot) and a
# single divergence. Kept as bare tuples on purpose: their only consumers are
# ``==`` (the diff) and ``repr`` (the shrunk Hypothesis counterexample), and a
# dataclass would make the printed counterexample noisier for no gain.
Observation = tuple
Divergence = tuple

# Reuse ``property_settings``' deadline / health-check policy (deadline off,
# ``too_slow`` suppressed); fewer examples than a single-adapter property because
# each example replays the whole history against two adapters.
parity_settings = settings(property_settings, max_examples=150)

# ``_names`` (printable ASCII minus the HTML-escaped ``& < >``) is shared from the
# ``strategies`` module; ``Account.name`` is ``max_length=50`` to match its
# ``max_size``.
_balances = st.integers(min_value=-50, max_value=50)


def _exc_class_tag(cls: type[BaseException]) -> str:
    """Tag an exception *class* by its fully-qualified name.

    The module is included so two same-named exceptions from different packages
    (a common clash, e.g. ``IntegrityError``) do not read as agreement and mask a
    real exception-type divergence. Tests derive their expected tags through this
    same function so a pin can never drift from what :func:`_exc_tag` records.
    """
    return f"err:{cls.__module__}.{cls.__qualname__}"


def _exc_tag(exc: Exception) -> str:
    """Record an exception by its *fully-qualified* class, never its message.

    Messages carry adapter-specific text, so comparing them would report spurious
    divergences; the class is the behavior two adapters must agree on.
    """
    return _exc_class_tag(type(exc))


def make_account_cls() -> type[BaseAggregate]:
    """A fresh ``Account`` aggregate class.

    Each domain gets its own class so that registering the same concept into two
    live domains cannot cross-bind element metadata.
    """

    class Account(BaseAggregate):
        name = String(max_length=50)
        balance = Integer(default=0)

    return Account


def build_parity_domain(
    provider_config: dict[str, typing.Any],
    *,
    bug: typing.Literal["lost_update", "dropped_balance"] | None = None,
) -> tuple[Domain, BaseRepository]:
    """Build a domain with a single ``Account`` aggregate on one provider.

    Returns the domain and its (already-materialized) repository; the repository
    is built once here rather than per replay, since ``_data_reset`` clears the
    *provider*, not the repository.

    ``bug`` swaps in a deliberately broken Memory DAO, used only to plant a
    Memory-vs-SQL divergence and prove the harness is not vacuous (see the
    seeded-divergence tests): ``"lost_update"`` skips the OCC version check,
    ``"dropped_balance"`` zeroes the balance on every write.
    """
    domain = Domain(
        name="Differential",
        config={
            "identity_type": "string",
            "databases": {"default": provider_config},
        },
    )
    account_cls = make_account_cls()
    domain.register(account_cls)
    domain.init(traverse=False)

    if bug is not None:
        _install_memory_bug(domain.providers["default"], bug)

    with domain.domain_context():
        repo = domain.repository_for(account_cls)
        _ = repo._dao  # materialize the model before creating tables
        domain.providers["default"]._create_database_artifacts()

    return domain, repo


class _LastWriteWinsDAO(DictDAO):
    """A Memory DAO that ignores the expected version on update.

    Forcing ``expected_version=None`` skips both the snapshot version check and
    the ``record_version_check`` call, so ``MemorySession.commit``'s compare-and-
    set finds nothing to reconcile: a stale write silently wins instead of
    raising ``ExpectedVersionError``. This is the :issue:`#1087` lost-update
    symptom, planted deliberately; it diverges on the concurrency / exception
    channel.
    """

    def _update(
        self, model_obj: typing.Any, expected_version: int | None = None
    ) -> typing.Any:
        return super()._update(model_obj, expected_version=None)


class _DroppedBalanceDAO(DictDAO):
    """A Memory DAO that zeroes the balance on every write.

    A shared-nothing data-corruption plant distinct from the OCC one: a correct
    adapter stores the written balance, this one stores ``0``, so a read, a
    filtered query, and the final-state snapshot all diverge from a correct
    adapter. It proves those observation channels are non-vacuous.
    """

    def _create(self, model_obj: typing.Any) -> typing.Any:
        model_obj["balance"] = 0
        return super()._create(model_obj)

    def _update(
        self, model_obj: typing.Any, expected_version: int | None = None
    ) -> typing.Any:
        model_obj["balance"] = 0
        return super()._update(model_obj, expected_version=expected_version)


_MEMORY_BUGS: dict[str, type[DictDAO]] = {
    "lost_update": _LastWriteWinsDAO,
    "dropped_balance": _DroppedBalanceDAO,
}


def _install_memory_bug(provider: MemoryProvider, bug: str) -> None:
    """Point a Memory provider instance at a broken DAO.

    Patches the instance's ``get_dao`` before any repository materializes its
    DAO, so every ``Account`` DAO the domain hands out is the broken one.
    """
    dao_cls = _MEMORY_BUGS[bug]

    def get_dao(
        entity_cls: type[typing.Any], database_model_cls: type[typing.Any]
    ) -> DictDAO:
        return dao_cls(provider.domain, provider, entity_cls, database_model_cls)

    provider.get_dao = get_dao  # type: ignore[method-assign]


# --- Operations -----------------------------------------------------------
#
# Each operation carries every input it needs (ids, field values), so the two
# adapters replay byte-identical work. ``apply`` returns a plain tuple describing
# the observable outcome; the exception *class* is recorded, never the message
# (messages carry adapter-specific text), so agreement is about behavior.


@dataclass(frozen=True)
class Add:
    id: str
    name: str
    balance: int

    def apply(self, repo: BaseRepository) -> Observation:
        account_cls = repo.meta_.part_of
        agg = account_cls(id=self.id, name=self.name, balance=self.balance)
        repo.add(agg)
        return ("add", self.id, agg._version)


@dataclass(frozen=True)
class Update:
    id: str
    balance: int

    def apply(self, repo: BaseRepository) -> Observation:
        # The generator only updates a live id, so a single-writer save succeeds;
        # any unexpected raise is caught and recorded by ``run_history`` so a
        # cross-adapter difference is diffed rather than crashing the replay.
        agg = repo.get(self.id)
        agg.balance = self.balance
        repo.add(agg)
        return ("update", self.id, agg._version)


@dataclass(frozen=True)
class ConcurrentUpdate:
    """Two writers load the same aggregate at one version and both try to save.

    The sequential form of the :issue:`#1087` race: the first save advances the
    version, the second still expects the old one. On an OCC-correct adapter the second
    raises ``ExpectedVersionError``; a lost-update adapter lets it through. Either
    way the outcome is recorded and diffed.
    """

    id: str
    balance_a: int
    balance_b: int

    def apply(self, repo: BaseRepository) -> Observation:
        first_writer = repo.get(self.id)
        second_writer = repo.get(self.id)

        first_writer.balance = self.balance_a
        repo.add(first_writer)
        first = first_writer._version

        try:
            second_writer.balance = self.balance_b
            repo.add(second_writer)
            second: typing.Any = second_writer._version
        except Exception as exc:
            second = _exc_tag(exc)
        return ("concurrent", self.id, first, second)


@dataclass(frozen=True)
class Read:
    id: str

    def apply(self, repo: BaseRepository) -> Observation:
        try:
            agg = repo.get(self.id)
            return ("read", self.id, agg.name, agg.balance, agg._version)
        except Exception as exc:
            return ("read", self.id, _exc_tag(exc))


@dataclass(frozen=True)
class Delete:
    id: str

    def apply(self, repo: BaseRepository) -> Observation:
        # The generator only deletes a live id, so the load always finds it.
        agg = repo.get(self.id)
        repo._dao.delete(
            agg
        )  # hard delete: the sanctioned escape hatch, no public alias
        return ("delete", self.id, "ok")


@dataclass(frozen=True)
class Query:
    """A filtered read: aggregates with ``balance >= threshold``.

    The result is normalized to a sorted list of ``(id, balance)`` so the
    comparison is over the *set* of matched rows, not any adapter's incidental
    row order (which is not a guarantee — see ``docs/reference/guarantees.md``).
    """

    threshold: int

    def apply(self, repo: BaseRepository) -> Observation:
        result = repo.query.filter(balance__gte=self.threshold).all()
        rows = sorted((item.id, item.balance) for item in result.items)
        return ("query", self.threshold, tuple(rows))


Operation = Add | Update | ConcurrentUpdate | Read | Delete | Query


@st.composite
def histories(draw: st.DrawFn) -> list[Operation]:
    """A randomized, well-defined history over a small pool of aggregates.

    The strategy tracks which ids are live while drawing so that ``update`` /
    ``concurrent`` / ``delete`` only ever target an existing aggregate and ``add``
    only ever targets a fresh id: every step has an outcome both a correct Memory
    and a correct SQL adapter must agree on. Ids are never reused after deletion,
    so no step depends on how an adapter treats an add over a tombstone.
    """
    operations: list[Operation] = []
    live: list[str] = []
    next_id = 0

    for _ in range(draw(st.integers(min_value=1, max_value=12))):
        # Only offer id-consuming operations when a live aggregate exists.
        kinds = ["add", "query", "read"]
        if live:
            kinds += ["update", "concurrent", "delete", "read_live"]
        kind = draw(st.sampled_from(kinds))

        if kind == "add":
            new_id = f"id{next_id}"
            next_id += 1
            operations.append(Add(new_id, draw(_names), draw(_balances)))
            live.append(new_id)
        elif kind == "update":
            operations.append(Update(draw(st.sampled_from(live)), draw(_balances)))
        elif kind == "concurrent":
            operations.append(
                ConcurrentUpdate(
                    draw(st.sampled_from(live)), draw(_balances), draw(_balances)
                )
            )
        elif kind == "delete":
            target = draw(st.sampled_from(live))
            live.remove(target)
            operations.append(Delete(target))
        elif kind == "read_live":
            operations.append(Read(draw(st.sampled_from(live))))
        elif kind == "read":
            # A read against an id that may or may not exist (fresh, live, or
            # already deleted); the two adapters must agree on the outcome either
            # way. ``read_live`` above covers the guaranteed-hit path; this one
            # lets misses happen too.
            operations.append(Read(f"id{draw(st.integers(0, next_id))}"))
        else:  # query
            operations.append(Query(draw(_balances)))

    return operations


def run_history(
    domain: Domain, repo: BaseRepository, history: list[Operation]
) -> list[Observation]:
    """Replay ``history`` against one adapter and return the step-by-step outcomes.

    Resets the provider first so each replay starts from an empty store, then
    appends a final snapshot of every surviving aggregate (id, name, balance,
    version) so divergences in end state are caught even when no per-step outcome
    differs.

    An operation that raises unexpectedly (one the generator meant to succeed) is
    recorded as a ``("raised", <class>)`` observation rather than propagated, so a
    divergence where only one adapter raises is diffed as an outcome instead of
    crashing the replay for whichever adapter happens to run first.
    """
    observations: list[Observation] = []
    with domain.domain_context():
        domain.providers["default"]._data_reset()
        for index, operation in enumerate(history):
            try:
                observations.append((index, *operation.apply(repo)))
            except Exception as exc:
                observations.append((index, "raised", _exc_tag(exc)))

        final = repo.query.all()
        snapshot = sorted(
            (item.id, item.name, item.balance, item._version) for item in final.items
        )
        observations.append(("final", tuple(snapshot)))
    return observations


def diff_observations(
    left: list[Observation], right: list[Observation]
) -> list[Divergence]:
    """Return the positions where two observation lists disagree.

    Each entry is ``(position, left_obs, right_obs)``. An empty list means the two
    adapters produced identical observable behavior for the history.
    """
    divergences: list[Divergence] = []
    # strict=False: a length mismatch is reported separately below, not raised —
    # an adapter that aborts a history early is a divergence to surface, not a
    # crash to swallow.
    for position, (left_obs, right_obs) in enumerate(zip(left, right, strict=False)):
        if left_obs != right_obs:
            divergences.append((position, left_obs, right_obs))
    if len(left) != len(right):
        divergences.append(("length", len(left), len(right)))
    return divergences


def format_divergences(history: list[Operation], divergences: list[Divergence]) -> str:
    """A readable report for an assertion message on a failing parity example."""
    lines = ["adapters diverged on history:"]
    lines += [f"  {operation}" for operation in history]
    lines.append("divergences (position, left, right):")
    lines += [f"  {divergence}" for divergence in divergences]
    return "\n".join(lines)
