# ADR-0027: The Unit of Work is a real database transaction

**Status:** Accepted

**Date:** July 2026

## Context

The PostgreSQL and MSSQL SQLAlchemy providers create their engine with
`isolation_level="AUTOCOMMIT"` and their session with `autoflush=False`. A Unit
of Work then gets its atomicity by buffering every write in the SQLAlchemy
session and flushing once, at the UoW's commit. Protean introduced this model
in 2019 (PR #220, "Unit of Work Enhancements"), and other parts of the
framework have depended on it since. The docs for the optimistic-concurrency
guard (ADR-0013, #1087/#1244) describe that guard in terms of this model.

The model was almost certainly chosen to keep database transactions short.
Writes live in Python memory, so the real DB transaction is open only briefly
at commit. That is a real benefit for lock contention. But to get that benefit,
the model gives up the guarantees that a Unit of Work exists to provide. We
measured the actual behavior against a running PostgreSQL instance. The model
appears to offer atomicity, but it delivers atomicity only in the simplest
case.

What we measured (empirical probes against real PostgreSQL):

1. A mid-UoW `session.flush()` commits immediately and durably. The explicit
   `session.begin()` the UoW issues creates only a SQLAlchemy logical
   transaction. The psycopg2 connection has `autocommit=True`. As a result, the
   driver commits each statement from a flush as soon as it sends the
   statement. A separate connection can see a flushed row before the UoW
   commits. The row also survives `session.rollback()`.

2. A child-bearing aggregate corrupts on rollback. When you add a `Post` with a
   `Comment` inside a UoW, the adapter forces a mid-UoW flush (it flushes the
   parent before syncing children). The parent row commits durably mid-UoW; the
   child rows do not. A later `uow.rollback()` therefore leaves an orphaned
   parent `Post` in the database with none of its children. That is a corrupted
   aggregate, not a clean rollback.

3. The commit itself is not atomic across tables. Take a UoW that writes to two
   tables. When the second write fails at the commit flush, the first write
   stays durably committed. We proved this with an `INSERT` into one table plus
   a failing optimistic-concurrency `UPDATE` on another: the `INSERT` persisted
   even though the UoW commit raised. So the transactional outbox is not
   atomic. A domain write and its outbox message can split. The outbox pattern
   exists to prevent exactly that split.

4. The only atomic case is a single-statement UoW: one childless, UUID-keyed
   aggregate, which is buffered until commit and rolled back before any flush.
   The existing rollback tests cover only this single-statement case. For that
   reason, those tests pass while the atomicity defect is present.

5. Read-your-writes inside a UoW is broken (issue #1256). A criteria read
   (`filter`/`count`/`exists`) never flushes the session's pending writes, so
   it returns stale results on PostgreSQL and MSSQL. For the same reason,
   in-UoW uniqueness validation reads committed state. (A `get` after modifying
   an existing aggregate does see the change, because SQLAlchemy's identity map
   returns the in-memory object.) The criteria case cannot be fixed by flushing
   before reads, because that flush would be another durable, un-rollback-able
   mid-UoW write, per finding (1).

The root cause of all five is the same. With an AUTOCOMMIT engine, the database
commits every statement it receives immediately. As a result, "buffer and flush
once" only approximates a transaction for a single statement. Every mature ORM
and framework avoids this by mapping the Unit of Work onto a real database
transaction: SQLAlchemy's own default, Hibernate/JPA, Django's `atomic()`,
Entity Framework, Rails. Inside a real transaction, the database provides
atomicity, read-your-writes, and isolation. The application does not have to
re-implement them.

## Decision

A Unit of Work is one real database transaction. For the PostgreSQL and MSSQL
providers we will:

- Remove `isolation_level="AUTOCOMMIT"` from the engine and run at the default
  read-committed level (configurable).
- Set `autoflush=True` on the session (the SQLAlchemy default).
- Have each UoW own a single real `BEGIN ... COMMIT/ROLLBACK`, so every write
  (parent, child, auto-increment, and outbox message) is deferred within that
  transaction and committed or rolled back as one unit.
- Make a nested UnitOfWork (one started while another is active on the same
  context) join the outermost transaction rather than open its own. Protean
  uses no savepoints, so the nested UoW does not push onto the context stack,
  and its commit/rollback defer to the outermost UoW. A nested rollback forces
  the whole transaction to roll back.

With the UoW as a real transaction, the database provides each of the following
guarantees:

- Read-your-writes: `autoflush` flushes pending changes before a query, inside
  the transaction, so a read sees the UoW's own writes. A `ROLLBACK` undoes
  those writes (this fixes the read-your-writes bug, #1256).
- Full atomicity: multi-table, child-bearing, and outbox writes are
  all-or-nothing, so a rollback no longer leaves an orphaned parent or splits a
  domain write from its outbox message.
- Optimistic concurrency: `version_id_col` in a real transaction is the designed
  SQLAlchemy use case. The `WHERE _version = :loaded` guard runs as part of the
  real flush and raises when a concurrent write has incremented the version. It
  gets simpler, not harder.
- Isolation: concurrent UoWs are isolated by the database, not by buffering.
- `_claim` (`SELECT ... FOR UPDATE SKIP LOCKED`) holds its row lock inside the
  transaction, rather than as an AUTOCOMMIT special case.

This ADR supersedes the AUTOCOMMIT-specific rationale in the
optimistic-concurrency ADR (ADR-0013), which reasoned that an eager statement
would autocommit mid-UoW. ADR-0013's optimistic-concurrency contract is
unchanged; only its transaction-model justification is replaced.

## Consequences

Positive:

- The Unit of Work becomes genuinely atomic for every relational aggregate shape,
  not just the single-statement case. Silent data-integrity failures (orphaned
  parents, split outbox writes) no longer occur within the relational store.
  (For an event-sourced aggregate, Protean still writes the event-store append
  as a separate durable record before the relational commit, as the event-store
  ADR (ADR-0015) describes. This split between the two stores is unchanged.)
- Read-your-writes works on PostgreSQL and MSSQL, matching the Memory and SQLite
  adapters and the behavior every other ORM provides.
- The adapter uses SQLAlchemy the way it is designed to be used. The OCC guard and
  `_claim` become standard rather than special cases.

Negative:

- A real transaction is held open for the UoW's duration, so its locks are too. That
  raises contention and connection-pool pressure for long UoWs. The mitigations
  are standard and are good DDD practice in any case. Limit a UoW to the work
  of a single use case, and do no external I/O (an API call, a broker publish)
  inside a UoW.
- This change modifies the Unit of Work subsystem, which many parts of Protean
  depend on. Recent work on optimistic concurrency (#1087/#1244) stabilized
  that subsystem. The maintainers must validate the change carefully before
  they ship it.

What can go wrong under the real-transaction model:

A real transaction has failure modes that the AUTOCOMMIT model hid. None of
these failure modes is new to this change. The Memory and SQLite adapters
already run each UoW as a real transaction (Memory via a copy-on-write session,
SQLite via SQLAlchemy's default autoflush), and we reproduced the same behavior
on both adapters. We found these failure modes when we made PostgreSQL and
MSSQL behave like the Memory and SQLite adapters. This change resolves the ones
the framework can fix and documents the rest as guidance.

Resolved in this change, for all adapters:

- Nested `UnitOfWork`. A nested UoW used to share the outer's session, so an inner
  commit durably persisted the outer's pending writes and an inner rollback discarded
  them. It now joins the outermost transaction (see the Decision above), so nesting
  is safe: only the outermost UoW commits or rolls back.
- An OCC conflict raised at an in-UoW read. With `autoflush=True` a read flushes
  pending writes first, so a version-guarded `UPDATE` can lose an optimistic-
  concurrency race at the read. That conflict used to appear as a raw
  `StaleDataError`, which the version-retry path missed. `filter` and `count`
  now translate it to `ExpectedVersionError`, matching the flush and commit
  paths.
- A reset-teardown deadlock. The test reset helper (`_data_reset`) deleted all tables
  before rolling back a leaked in-progress UoW, so a UoW holding row locks blocked the
  delete and deadlocked. It now rolls back the dangling UoW first.

Remaining as guidance (properties of any real transaction, not framework bugs):

- Prefer the `with UnitOfWork():` context manager. A manual `uow.start()`
  without a `try/finally` leaks the transaction (and its connection and locks)
  if an exception is raised before `commit()`/`rollback()`. Only the context
  manager guarantees cleanup on the exception path.
- Size the connection pool to peak UoW concurrency. Under multithreading each
  thread's UoW holds a pooled connection for the whole transaction. The async
  engine runs on a single event-loop thread, so it is not exposed to this pool
  pressure. A multithreaded host (a threaded WSGI worker, a user thread pool)
  is exposed to it.
- On MSSQL, the default read-committed isolation uses row locks instead of
  MVCC, so a reader can block on a writer holding a row inside a UoW.
  PostgreSQL would not block that reader. If that blocking is a problem, enable
  `READ_COMMITTED_SNAPSHOT` on the database for MVCC-style reads.

How the change is migrated and validated:

The change touches OCC (ADR-0013), `_claim`, `_commit_if_standalone`, the
standalone read/write paths, and the connection lifecycle. The change ships
with a property-test suite that runs on real PostgreSQL and MSSQL. The suite
encodes the guarantees the old model cannot meet. With the old AUTOCOMMIT
engine restored, the regression tests in these suites fail; on the fix they
pass
(`tests/adapters/repository/sqlalchemy_repo/postgresql/test_postgresql_uow_atomicity_and_ryw.py`
and its MSSQL mirror):

- read-your-writes inside a UoW for `filter`, `count`, and `exists`, and for an
  update that emits SQL;
- both directions of a multi-table and child-bearing UoW: a rollback leaves no
  orphaned parent, and a commit persists parent and children together;
- a cross-table commit being atomic (a failure in one table leaves neither).
  This is the transactional-outbox shape. The outbox row is saved on the same
  session and committed by the same `session.commit()` as the domain write, so
  the cross-table test's guarantee carries to the outbox;
- on PostgreSQL, a pending write staying invisible to a separate connection until
  commit;
- an OCC conflict raised at an in-UoW read surfacing `ExpectedVersionError` rather
  than a raw `StaleDataError`;
- optimistic concurrency continues to hold (the existing OCC and `_claim`
  concurrency tests pass under the real-transaction model).

`tests/unit_of_work/test_nested_unit_of_work.py` covers nested-UoW behavior
separately. Its tests show that a nested UoW joins the outermost transaction:
commit-all, outer-rollback-after-inner-commit, exception-in-inner, and
explicit-inner-rollback all leave the store consistent.

## Alternatives Considered

- Document the limitation as intentional. Rejected: the measured behavior is
  data-corruption-class (orphaned aggregates, split outbox writes), not a cosmetic
  caveat. "Read-your-writes is not guaranteed" is a defensible thing to document. "A
  rolled-back UnitOfWork can leave a half-written aggregate" is not.

- Partial read-your-writes via the session identity map. Serve `get`-by-id and
  modified-entity reads from the identity map without flushing. Rejected: the
  identity map does nothing for `filter`/`count`/`exists`, because those reads
  emit SQL, and SQL cannot see unflushed writes without an unsafe flush. As a
  result, this option half-fixes the read-your-writes bug (#1256) and leaves
  in-UoW reads inconsistent, some seeing the UoW's writes and some not.

- Keep AUTOCOMMIT but wrap each UoW in an explicit real transaction, with autoflush
  still off. Rejected: opening a real transaction is the decision above. Dropping
  AUTOCOMMIT is the clean way to express it. Leaving autoflush off would keep
  read-your-writes broken for no benefit.

- Support independent inner transactions (savepoints, or a suspend-and-new inner
  transaction). This is what a nested UoW joining the outermost gives up: an
  inner scope cannot commit or roll back on its own. Rejected as a non-goal. It
  cannot be offered uniformly (the Memory adapter has no savepoints and
  Elasticsearch has no transactions), so it would break the "write once, run on
  any adapter" promise; it adds real complexity (savepoint stacks,
  partial-rollback semantics, connection suspension, adapter-specific paths);
  and it is an infrastructure concern that does not belong in a domain-layer
  Unit of Work. The aggregate is the consistency boundary. One UoW maps to one
  use case. You coordinate work across aggregates with domain events. A durable
  side-effect that must survive a rollback goes through the outbox or a write
  outside the UoW. Nesting is not forbidden, because forbidding it would break
  legitimate composition, such as an application service called from a command
  handler. A nested UoW joins the outermost transaction, so you get the correct
  single-transaction behavior automatically.
