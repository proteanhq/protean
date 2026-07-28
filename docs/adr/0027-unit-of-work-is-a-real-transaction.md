# ADR-0027: The Unit of Work is a real database transaction

**Status:** Accepted

**Date:** July 2026

## Context

The PostgreSQL and MSSQL SQLAlchemy providers create their engine with
`isolation_level="AUTOCOMMIT"` and their session with `autoflush=False`. A Unit of
Work then gets its atomicity by buffering every write in the SQLAlchemy session and
flushing once, at the UoW's commit. This model was introduced in 2019 (PR #220,
"Unit of Work Enhancements") and has been load-bearing since; the
optimistic-concurrency guard (ADR-0013, #1087/#1244) is documented in terms of it.

The model was almost certainly chosen to keep database transactions short. Writes
live in Python memory, so the real DB transaction is open only briefly at commit.
That is a real benefit for lock contention. But it pays for that benefit by giving
up the guarantees a Unit of Work exists to provide. We measured the actual behavior
against a running PostgreSQL instance, and the atomicity it appears to offer holds
only for the simplest case.

What we measured (empirical probes against real PostgreSQL):

1. A mid-UoW `session.flush()` commits immediately and durably. The explicit
   `session.begin()` the UoW issues creates only a SQLAlchemy logical transaction.
   The psycopg2 connection has `autocommit=True`, so each statement a flush emits is
   committed at the driver level the moment it is sent. A flushed row is visible to
   a separate connection before the UoW commits, and it survives `session.rollback()`.

2. A child-bearing aggregate corrupts on rollback. Adding a `Post` with a `Comment`
   inside a UoW forces a mid-UoW flush (the adapter flushes the parent before syncing
   children). The parent row commits durably mid-UoW; the child rows do not. A later
   `uow.rollback()` therefore leaves an orphaned parent `Post` in the database with
   none of its children. That is a corrupted aggregate, not a clean rollback.

3. The commit itself is not atomic across tables. A UoW that writes to two tables,
   where the second write fails at the commit flush, leaves the first write durably
   committed. We proved this with an `INSERT` into one table plus a failing
   optimistic-concurrency `UPDATE` on another: the `INSERT` persisted even though the
   UoW commit raised. So the transactional outbox is not atomic. A domain write and
   its outbox message can split, which defeats the reason the outbox pattern exists.

4. The only atomic case is a single-statement UoW: one childless, UUID-keyed
   aggregate, which is buffered until commit and rolled back before any flush. That
   is the shape the existing rollback tests cover, which is why they pass while the
   hole is present.

5. Read-your-writes inside a UoW is broken (issue #1256). A criteria read
   (`filter`/`count`/`exists`) never flushes the session's pending writes, so it
   returns stale results on PostgreSQL and MSSQL, and in-UoW uniqueness validation
   reads committed state. (A `get` after modifying an existing aggregate does see the
   change, because SQLAlchemy's identity map returns the in-memory object.) The
   criteria case cannot be fixed by flushing before reads, because that flush would
   be another durable, un-rollback-able mid-UoW write, per finding (1).

The root cause of all five is the same. With an AUTOCOMMIT engine, any statement
that reaches the database is committed immediately, so "buffer and flush once" only
approximates a transaction for a single statement. Every mature ORM and framework
avoids this by mapping the Unit of Work onto a real database transaction:
SQLAlchemy's own default, Hibernate/JPA, Django's `atomic()`, Entity Framework,
Rails. Inside a real transaction, atomicity, read-your-writes, and isolation are
properties you get from the database, not ones the application re-implements.

## Decision

A Unit of Work is one real database transaction. For the PostgreSQL and MSSQL
providers we will:

- Remove `isolation_level="AUTOCOMMIT"` from the engine and run at the default
  read-committed level (configurable).
- Set `autoflush=True` on the session (the SQLAlchemy default).
- Have each UoW own a single real `BEGIN ... COMMIT/ROLLBACK`, so every write
  (parent, child, auto-increment, and outbox message) is deferred within that
  transaction and committed or rolled back as one unit.

With the UoW as a real transaction, each guarantee comes from the database:

- Read-your-writes: `autoflush` flushes pending changes before a query, inside the
  transaction, so a read sees the UoW's own writes, and a `ROLLBACK` undoes them
  (#1256 fixed).
- Full atomicity: multi-table, child-bearing, and outbox writes are all-or-nothing,
  so the orphaned-parent and split-outbox holes close.
- Optimistic concurrency: `version_id_col` in a real transaction is the designed
  SQLAlchemy use case. The `WHERE _version = :loaded` guard rides the real flush and
  raises on a concurrent bump. It gets simpler, not harder.
- Isolation: concurrent UoWs are isolated by the database, not by buffering.
- `_claim` (`SELECT ... FOR UPDATE SKIP LOCKED`) holds its row lock inside the
  transaction, rather than as an AUTOCOMMIT special case.

This supersedes the AUTOCOMMIT-specific rationale in ADR-0013 (the reasoning that an
eager statement would autocommit mid-UoW). ADR-0013's optimistic-concurrency
contract is unchanged; only its transaction-model justification is replaced.

## Consequences

Positive:

- The Unit of Work becomes genuinely atomic for every relational aggregate shape,
  not just the single-statement case. Silent data-integrity failures (orphaned
  parents, split outbox writes) go away. (For an event-sourced aggregate the
  event-store append is still a separate durable anchor written before the
  relational commit, per ADR-0015; that two-store boundary is unchanged.)
- Read-your-writes works on PostgreSQL and MSSQL, matching the Memory and SQLite
  adapters and the behavior every other ORM provides.
- The adapter uses SQLAlchemy the way it is designed to be used. The OCC guard and
  `_claim` become standard rather than special cases.

Negative:

- A real transaction is held open for the UoW's duration, so its locks are too. That
  raises contention and connection-pool pressure for long UoWs. The mitigations are
  standard and are good DDD practice regardless: keep a UoW to a single use-case's
  worth of work, and do no external I/O (an API call, a broker publish) inside a UoW.
- This changes a load-bearing subsystem that #1087/#1244 recently stabilized. It
  must be validated carefully, not shipped casually.

Sharp edges of the real-transaction model:

A real transaction has sharp edges that the AUTOCOMMIT model hid. These are not new
to this change. The Memory and SQLite adapters already run each UoW as a real
transaction (Memory via a copy-on-write session, SQLite via SQLAlchemy's default
autoflush), so they already behave this way today; we verified each edge below
reproduces on them. This change brings PostgreSQL and MSSQL into line with them
rather than introducing new behavior. They are written down here so the behavior is
understood, and hardening them is tracked as follow-up work.

- Nested `UnitOfWork` on the same thread shares one session. An inner UoW's commit
  or rollback acts on the outer UoW's writes too, so an inner commit can durably
  persist the outer's pending writes and an inner rollback can undo them. Ordinary
  handler code does not nest (repository writes reuse the active UoW), but explicit
  `with UnitOfWork(): ... with UnitOfWork():` in user code is unsafe.
- A manual `uow.start()` without a `try/finally` leaks the transaction (and its
  connection and locks) if an exception is raised before `commit()`/`rollback()`.
  Only the `with UnitOfWork():` context manager guarantees cleanup on the exception
  path. Prefer the context manager.
- Under multithreading, each thread's UoW holds a pooled connection for the whole
  transaction, so size the connection pool to peak UoW concurrency. The async
  engine runs on a single event-loop thread and is not exposed to this; a
  multithreaded host (a threaded WSGI worker, a user thread pool) is.
- On MSSQL the default read-committed isolation uses row locks, not MVCC, so a
  reader on one connection can block on a writer holding a row inside a UoW where
  PostgreSQL would not. Enabling `READ_COMMITTED_SNAPSHOT` on the database gives
  MSSQL MVCC-style reads if that blocking is a problem.
- With `autoflush=True`, an optimistic-concurrency conflict can surface at an
  in-UoW read (the read autoflushes the pending guarded `UPDATE`) as a raw
  `StaleDataError`, earlier than the commit where the version-retry path catches it.
  Extending the retry path to catch this earlier surface is follow-up work.

Migration and validation:

The change touches OCC (ADR-0013), `_claim`, `_commit_if_standalone`, the standalone
read/write paths, and the connection lifecycle. It ships with a property-test suite
on real PostgreSQL and MSSQL that encodes the guarantees the old model cannot meet.
With the old AUTOCOMMIT engine restored, the regression tests in these suites go red;
on the fix they pass
(`tests/adapters/repository/sqlalchemy_repo/postgresql/test_postgresql_uow_atomicity_and_ryw.py`
and its MSSQL mirror):

- read-your-writes inside a UoW for `filter`, `count`, and `exists`, and for an
  update that emits SQL;
- both directions of a multi-table and child-bearing UoW: a rollback leaves no
  orphaned parent, and a commit persists parent and children together;
- a cross-table commit being atomic (a failure in one table leaves neither). This is
  the transactional-outbox shape: the outbox row is saved on the same session and
  committed by the same `session.commit()` as the domain write, so the cross-table
  test's guarantee carries to the outbox;
- on PostgreSQL, a pending write staying invisible to a separate connection until
  commit;
- optimistic concurrency continues to hold (the existing OCC and `_claim`
  concurrency tests pass under the real-transaction model).

## Alternatives Considered

- Document the limitation as intentional. Rejected: the measured behavior is
  data-corruption-class (orphaned aggregates, split outbox writes), not a cosmetic
  caveat. "Read-your-writes is not guaranteed" is a defensible thing to document. "A
  rolled-back UnitOfWork can leave a half-written aggregate" is not.

- Partial read-your-writes via the session identity map. Serve `get`-by-id and
  modified-entity reads from the identity map without flushing. Rejected: it does
  nothing for `filter`/`count`/`exists` (those emit SQL that cannot see unflushed
  writes without an unsafe flush), so it half-fixes #1256 and leaves in-UoW reads
  inconsistent, some seeing the UoW's writes and some not.

- Keep AUTOCOMMIT but wrap each UoW in an explicit real transaction, with autoflush
  still off. Rejected: opening a real transaction is the decision above. Dropping
  AUTOCOMMIT is the clean way to express it. Leaving autoflush off would keep
  read-your-writes broken for no benefit.
