# Mutation Testing

Line and branch coverage tell you which code ran during the tests. They do not
tell you whether a test would *notice* if that code were wrong. Mutation testing
closes that gap: it makes small, deliberate changes to the source (a "mutant",
for example flipping `<` to `<=` or `+ 1` to `- 1`) and re-runs the tests. If a
mutant makes no test fail, it "survived", which means that line is executed but
under-asserted. Every surviving mutant is a candidate for a new test.

Protean runs mutation testing as a periodic, targeted pass over the framework's
own core rather than as a CI gate. The goal is to harden the test suite module
by module, not to chase a global percentage.

## Running it

```shell
make mutation                       # default target: the outbox module
make mutation TARGET=entity         # a different module
MUT_FILTER="_run_invariants|_validate_status_transition" make mutation TARGET=entity
```

Targets currently defined include `outbox`, `entity`, `status-field`,
`event-sourcing`, `repositories-dao`, `upcaster`, `unit-of-work` (the transaction
boundary), `sync-dispatch` (breadth-first synchronous event dispatch, ADR-0016),
and `checkpoint` (the `$all` gap-safe checkpoint path in the event-store
subscription).

`checkpoint` mutates a large module (`event_store_subscription.py`), so it is
the slowest target: mutmut mutates the whole file. `MUT_FILTER` does not change
that. It narrows the printed **survivor list** to the checkpoint methods so
they are easy to pick out of the report (see "Reading the report" below). What
keeps the run tractable is the tight test subset the target already uses.

```shell
MUT_FILTER="update_read_position|update_current_position_to_store|_gap_safe_batch|_write_recovery_checkpoint" \
  make mutation TARGET=checkpoint
```

`make mutation` delegates to [`scripts/mutation.sh`](https://github.com/proteanhq/protean/blob/main/scripts/mutation.sh),
which:

1. Builds a dedicated Python 3.12 environment at `.venv-mutation` (see the
   caveat below). The project `.venv` is never touched.
2. Mutates the target module and runs a **fast subset** of its unit tests
   against each mutant, not the whole suite. A per-module subset keeps a run to
   a few minutes.
3. Prints a mutation score and the list of surviving mutants.

It uses [mutmut](https://github.com/boxed/mutmut) 3.x, which copies the source
tree into a `./mutants/` directory and runs the tests against the copy, so the
real source is never edited in place. The script cleans up `mutants/` (and the
temporary `setup.cfg` it writes for mutmut's config) when it finishes.

### Adding a target

Targets live in a `case` block in `scripts/mutation.sh`. Each maps a name to a
module and the fast test subset that exercises it. Pick the smallest set of tests
that covers the module's behaviour; a broad subset only slows the run without
finding more survivors.

## Reading the report

The report ends with a score and a list of survivors:

```
MUTATION SCORE: 83.6%  (422/505 killed; 34 lines had no covering test)

SURVIVORS: 83 (inspect one with: ... -m mutmut show <name>)
  protean.utils.outbox.xǁOutboxǁstart_processing__mutmut_1: survived
  ...
```

Mutant names are function-scoped (`…ǁClassǁmethod__mutmut_N`), so `MUT_FILTER` (a
grep pattern on the names) narrows the printed survivor list to one area, handy
on a large module where you only care about a few methods. It filters the
report, not the run: mutmut still mutates the whole target module and runs the
full subset. Inspect any single survivor with `mutmut show <name>` to see the exact change.

For each survivor, decide which of three buckets it falls into:

- **A real gap**: A behaviour that a test should pin but does not. Write the
  test, then re-run to confirm the mutant is now killed. This is the whole point
  of the exercise.
- **An equivalent mutant**: A change that cannot alter observable behaviour, so
  no test can kill it. The classic case in Protean is a `<` to `<=` flip on a
  `datetime.now()` comparison: the two differ only at the exact boundary
  instant, which a wall-clock test can never hit. These are killable only by
  freezing the clock to that instant (see the boundary tests in
  `tests/outbox/test_outbox_aggregate.py`), and are worth a test only when the
  boundary semantics are meaningful.
- **Low value**: Pinning a constant default (for example that a page size is
  exactly 50) is brittle and catches no realistic bug. Skip these deliberately
  rather than writing a test that only restates the literal.

Prefer killing behavioural survivors (wrong comparison, dropped filter,
off-by-one, swapped branch) over cosmetic ones. When you skip a survivor, a
one-line note in the PR description on *why* keeps the next pass honest.

!!! warning "Clear `__pycache__` if you hand-edit the real source to check a mutant"

    `make mutation` is safe here: mutmut mutates a copy under `./mutants/`, never
    the real tree. But if you sanity-check a survivor by editing the real source
    directly (flip the operator, run the test, restore it), clear `__pycache__`
    afterward: `find src tests -name __pycache__ -type d -exec rm -rf {} +`.
    CPython's default `.pyc` validation is timestamp-based (source mtime + size).
    A same-size flip such as `==` to `!=` restored within the same filesystem
    mtime-second leaves a `.pyc` whose recorded `(mtime, size)` still matches the
    restored source, so Python keeps running the *mutant* bytecode. The symptom is
    a broad, baffling set of failures (here: every sync inline-dispatch test) that
    vanish the moment you touch the file, with `git diff` showing nothing.

## Cadence

Treat this as a **quarterly pass**: pick one or two core modules, drive their
score up by adding the missing tests, and land the tests (never a lowered
threshold). `utils/outbox.py` and `core/upcaster.py` have had a full measured
pass driven to completion.

`core/unit_of_work.py` (the transaction boundary), `utils/sync_dispatch.py`
(breadth-first dispatch), and the checkpoint path in
`server/subscription/event_store_subscription.py` now have their own targets, and
tests that pin the highest-value behavioural mutants on each (the sync/async
commit-dispatch guard, the fan-out drain and `None`-context branch, the two
position-write cadence decisions). Running each target to completion and driving
down whatever survivors remain, `sync-dispatch` is close; `unit-of-work` and `checkpoint` still have uncovered
regions (partition-key routing, the recovery-checkpoint writer, `_gap_safe_batch`), is a good
next quarterly pass.

Some survivors in these paths are deliberately left alive because no test can
kill them without restating a literal or freezing the clock to a single instant:

- **Gap-timeout boundary** (`_gap_safe_batch`): `now - first_seen < gap_timeout_seconds`
  compares elapsed time on the monotonic clock (`time.monotonic()`), so a `<` to
  `<=` flip differs only at the exact timeout instant, an equivalent mutant in
  practice, the same class as the `datetime.now()` boundaries in the outbox module.
- **Default cadence constants**: Pinning that the default `position_update_interval`
  or `gap_timeout_seconds` is a specific number catches no realistic bug; the
  behaviour that matters (persist *at* the interval, hold *until* the timeout) is
  tested instead.

## Why a separate Python 3.12 environment

The tool runs in a dedicated `.venv-mutation` at **Python 3.12**, not the
project's Python 3.14, and this is deliberate. Python 3.14 is currently too
bleeding-edge for reliable mutation testing of Protean's compiled dependencies
(SQLAlchemy's C extensions, greenlet, and friends): under 3.14, mutmut's forked
workers segfault on roughly a fifth of mutants, so the results are incomplete.
Python 3.12 runs the whole set cleanly, and because the mutated logic is
version-independent the results are representative of every supported version.
Keeping the tool in its own environment also means `import protean` never pulls
in the mutation-only dependency for normal development.
