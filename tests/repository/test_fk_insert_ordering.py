"""Tests for the parent-before-child flush cascade in ``repository.add``.

Protean does not emit SQLAlchemy ``ForeignKey``/``relationship`` metadata for
``Reference`` fields, so the ORM cannot order parent-before-child inserts at
commit-time flush on its own. ``_do_add`` / ``_sync_children`` therefore call
``BaseDAO._flush()`` after each parent level so the parent row materializes in
the transaction before its FK-referencing children are written.

Two layers of coverage:

* ``TestFlushCascadeOrdering`` — provider-agnostic core tests that spy on the
  no-op ``_flush`` hook to assert it fires once per parent level. These fail
  without the fix and need no database.
* ``TestForeignKeyInsertOrdering`` — ``@pytest.mark.database`` tests that hook
  SQLAlchemy's ``before_cursor_execute`` (via ``capture_queries``) to assert the
  *actual* SQL INSERT order is top-down. The child classes are deliberately named
  to sort *before* their parent (``Coin`` < ``Vault``, ``Badge`` < ``Locker``,
  ``Area`` < ``Spot`` < ``Zone``) so that, absent the flush, the ORM's mapper-order
  emits the child INSERT first and the assertion goes red.

  These are a real fail-without-fix guard on **autoflush=False** providers
  (``MssqlProvider`` / ``PostgresqlProvider`` — see ``sqlalchemy.py``): with
  nothing flushing early, disabling the ``_flush`` cascade makes the commit emit
  children before parents (verified on MSSQL — child-first order). On **SQLite**
  they pass either way, because ``SqliteProvider`` leaves ``autoflush`` at its
  default ``True``, so the per-save existence-check ``SELECT`` incidentally
  flushes the parent row before each child regardless of the fix. Postgres, which
  runs in the standard CI matrix, exercises them as a genuine guard.
"""

import re

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.unit_of_work import UnitOfWork
from protean.fields import HasMany, HasOne, Integer, Reference, String
from protean.integrations.pytest import capture_queries
from protean.utils.globals import current_domain


# --- HasMany: Vault (root) -> Coin (child) --------------------------------
class Vault(BaseAggregate):
    name: String(required=True)
    coins = HasMany("tests.repository.test_fk_insert_ordering.Coin")


class Coin(BaseEntity):
    denomination: Integer(default=1)
    vault = Reference("tests.repository.test_fk_insert_ordering.Vault")


# --- HasOne: Locker (root) -> Badge (child) -------------------------------
class Locker(BaseAggregate):
    name: String(required=True)
    badge = HasOne("tests.repository.test_fk_insert_ordering.Badge")


class Badge(BaseEntity):
    code: String(required=True)
    locker = Reference("tests.repository.test_fk_insert_ordering.Locker")


# --- Grandchild: Zone (root) -> Area (child) -> Spot (grandchild) ----------
class Zone(BaseAggregate):
    name: String(required=True)
    areas = HasMany("tests.repository.test_fk_insert_ordering.Area")


class Area(BaseEntity):
    name: String(required=True)
    spots = HasMany("tests.repository.test_fk_insert_ordering.Spot")
    zone = Reference("tests.repository.test_fk_insert_ordering.Zone")


class Spot(BaseEntity):
    label: String(required=True)
    area = Reference("tests.repository.test_fk_insert_ordering.Area")


class Plain(BaseAggregate):
    """Aggregate with no child associations."""

    name: String(required=True)
    count: Integer(default=0)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Vault)
    test_domain.register(Coin, part_of=Vault)
    test_domain.register(Locker)
    test_domain.register(Badge, part_of=Locker)
    test_domain.register(Zone)
    test_domain.register(Area, part_of=Zone)
    test_domain.register(Spot, part_of=Area)
    test_domain.register(Plain)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# INSERT-order helpers
# ---------------------------------------------------------------------------
_INSERT_INTO = re.compile(r"INSERT\s+INTO\s+([^\s(]+)", re.IGNORECASE)


def _inserted_tables(captured):
    """Return the target table of each captured INSERT, in emission order.

    Names are lowercased with any schema prefix and quoting/bracketing stripped,
    so the check works across SQLite (``coin``), PostgreSQL (``public.coin``) and
    MSSQL (``[dbo].[coin]``).
    """
    tables = []
    for statement, _params in captured:
        match = _INSERT_INTO.search(statement)
        if match:
            name = match.group(1).rsplit(".", 1)[-1]
            tables.append(name.strip('"`[]').lower())
    return tables


def _assert_top_down(captured, *expected):
    """Assert each parent table's INSERT precedes its child's.

    On the in-memory backend there is no engine for ``capture_queries`` to hook,
    so nothing is captured and the check is skipped. On a real SQL backend an
    empty capture means the ``before_cursor_execute`` hook never fired: that is a
    broken test, so fail loudly instead of passing silently.
    """
    tables = _inserted_tables(captured)
    if not tables:
        engine = getattr(current_domain.providers["default"], "_engine", None)
        assert engine is None, (
            "no INSERTs captured on a SQL backend; capture_queries hook did not fire"
        )
        return
    positions = []
    for table in expected:
        assert table in tables, f"no INSERT INTO {table}; captured {tables}"
        positions.append(tables.index(table))
    assert positions == sorted(positions), (
        f"expected top-down INSERT order {list(expected)}, got {tables}"
    )


# ---------------------------------------------------------------------------
# Provider-agnostic core tests: spy on the no-op _flush hook
# ---------------------------------------------------------------------------
@pytest.fixture
def flush_spy(monkeypatch):
    """Count ``_flush`` calls on every DAO routed through a repository.

    Returns a dict with a mutable counter so a test can assert how many flushes
    the cascade issued.
    """
    from protean.port.dao import BaseDAO

    counter = {"count": 0}
    original = BaseDAO._flush

    def spy(self):
        counter["count"] += 1
        return original(self)

    monkeypatch.setattr(BaseDAO, "_flush", spy)
    return counter


class TestFlushCascadeOrdering:
    def test_single_level_children_trigger_one_flush(self, flush_spy):
        vault = Vault(name="v")
        vault.add_coins(Coin(denomination=1))
        vault.add_coins(Coin(denomination=2))

        current_domain.repository_for(Vault).add(vault)

        # One flush: after the root Vault is saved, before the Coin inserts.
        assert flush_spy["count"] == 1

    def test_has_one_child_triggers_one_flush(self, flush_spy):
        locker = Locker(name="l")
        locker.badge = Badge(code="b")

        current_domain.repository_for(Locker).add(locker)

        assert flush_spy["count"] == 1

    def test_two_level_children_trigger_flush_per_level(self, flush_spy):
        zone = Zone(name="z")
        area = Area(name="a")
        area.add_spots(Spot(label="s"))
        zone.add_areas(area)

        current_domain.repository_for(Zone).add(zone)

        # Flush after the root Zone (before the Area insert) and again before
        # descending into the Area's Spot grandchildren.
        assert flush_spy["count"] == 2

    def test_childless_aggregate_does_not_flush(self, flush_spy):
        current_domain.repository_for(Plain).add(Plain(name="solo"))

        assert flush_spy["count"] == 0


# ---------------------------------------------------------------------------
# End-to-end tests: assert the real SQL INSERT order is top-down
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.basic_storage
@pytest.mark.usefixtures("db")
class TestForeignKeyInsertOrdering:
    """Assert the *actual* SQL INSERT order is parent-before-child.

    ``basic_storage`` brings these onto the real relational backends in CI (they
    no-op on the in-memory backend, where ``capture_queries`` observes nothing).
    A genuine fail-without-fix guard on autoflush=False providers (MSSQL,
    Postgres); see the module docstring for why SQLite passes either way.
    """

    def test_parent_inserted_before_has_many_children(self):
        vault = Vault(name="v")
        vault.add_coins(Coin(denomination=1))
        vault.add_coins(Coin(denomination=2))

        with capture_queries() as captured:
            with UnitOfWork():
                current_domain.repository_for(Vault).add(vault)

        _assert_top_down(captured, "vault", "coin")

        refreshed = current_domain.repository_for(Vault).get(vault.id)
        assert len(refreshed.coins) == 2

    def test_parent_inserted_before_has_one_child(self):
        locker = Locker(name="l")
        locker.badge = Badge(code="b")

        with capture_queries() as captured:
            with UnitOfWork():
                current_domain.repository_for(Locker).add(locker)

        _assert_top_down(captured, "locker", "badge")

        refreshed = current_domain.repository_for(Locker).get(locker.id)
        assert refreshed.badge is not None

    def test_grandchild_inserted_top_down(self):
        zone = Zone(name="z")
        area = Area(name="a")
        area.add_spots(Spot(label="s"))
        zone.add_areas(area)

        with capture_queries() as captured:
            with UnitOfWork():
                current_domain.repository_for(Zone).add(zone)

        _assert_top_down(captured, "zone", "area", "spot")

        refreshed = current_domain.repository_for(Zone).get(zone.id)
        assert len(refreshed.areas) == 1
        assert len(refreshed.areas[0].spots) == 1
