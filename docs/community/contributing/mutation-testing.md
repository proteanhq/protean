# Mutation Testing

Line and branch coverage tell you which code ran during the tests. They do not
tell you whether a test would *notice* if that code were wrong. Mutation
testing checks whether a test would notice. It makes small, deliberate changes
to the source (a "mutant", for example flipping `<` to `<=` or `+ 1` to `- 1`)
and re-runs the tests. If a mutant makes no test fail, it "survived". A
surviving mutant means the tests execute that line but do not assert enough
about it. Every surviving mutant is a candidate for a new test.

Protean runs mutation testing as a periodic, targeted pass over the framework's
own core rather than as a CI gate. The goal is to add the missing tests one
module at a time. A global percentage is not the target.

## Running it

```shell
make mutation                       # default target: the outbox module
make mutation TARGET=entity         # a different module
MUT_FILTER="_run_invariants|_validate_status_transition" make mutation TARGET=entity
```

Targets currently defined include `outbox`, `entity`, `status-field`,
`event-sourcing`, `repositories-dao`, `upcaster`, `unit-of-work` (the transaction
boundary), `sync-dispatch` (breadth-first synchronous event dispatch, ADR-0016),
`checkpoint` (the `$all` gap-safe checkpoint path in the event-store
subscription), and five targets for the IR and the Observatory: `ir-builder`,
`ir-diff`, `observatory-api`, `observatory-timeline` and `observatory-metrics`
(see "IR and Observatory targets" below).

`checkpoint` mutates a large module (`event_store_subscription.py`), so it is
one of the slower targets: mutmut mutates the whole file. `MUT_FILTER` does not
change that. It narrows the printed **survivor list** to the checkpoint methods
so they are easy to pick out of the report (see "Reading the report" below).
The target's small test subset keeps the run short enough to finish.

```shell
MUT_FILTER="update_read_position|update_current_position_to_store|_gap_safe_batch|_write_recovery_checkpoint" \
  make mutation TARGET=checkpoint
```

`make mutation` delegates to [`scripts/mutation.sh`](https://github.com/proteanhq/protean/blob/main/scripts/mutation.sh),
which:

1. Builds a dedicated Python 3.12 environment at `.venv-mutation` (see the
   caveat below). The project `.venv` is never touched.
2. Mutates the target module and runs a **fast subset** of its unit tests
   against each mutant, not the whole suite. A per-module subset keeps most runs to
   a few minutes. `ir-builder`, the largest module, takes about half an hour.
3. Prints a mutation score and the list of surviving mutants.

It uses [mutmut](https://github.com/boxed/mutmut) 3.x, which copies the source
tree into a `./mutants/` directory and runs the tests against the copy. The
real source is never edited in place. The script writes a temporary `setup.cfg`
for mutmut's config. When it finishes, the script removes `mutants/` and that
`setup.cfg`.

### Adding a target

`scripts/mutation.sh` defines the targets in a `case` block. Each maps a name
to a module and the fast test subset that exercises it. Pick the smallest set
of tests that covers the module's behaviour; a broad subset only slows the run
without finding more survivors. Drop a test file the module never runs. mutmut
runs each mutant only against the tests that call the mutated function, so such
a file does not slow the per-mutant runs. It does add time to mutmut's two
whole-subset runs at the start: the run that records which tests call which
function, and the clean run on unmutated code. To check a file, run it alone in
`.venv-mutation` under coverage and read the module's line in the report:

```shell
.venv-mutation/bin/python -m coverage erase
.venv-mutation/bin/python -m coverage run -m pytest <file>
.venv-mutation/bin/python -m coverage combine
.venv-mutation/bin/python -m coverage report --include=<module>
```

The project's coverage settings write one data file per process, so `coverage
combine` has to run before `coverage report`. Those files stay on disk between
runs. `coverage combine` merges every one it finds, so `coverage erase` comes
first. Without it, data left by an earlier run can credit the file with lines
it never ran. The settings also turn on branch coverage, so the `Cover` column
mixes statements and branches. The coverage figures below are statement
coverage, computed from the report's `Stmts` and `Miss` columns as (Stmts −
Miss) / Stmts.

### IR and Observatory targets

| Target | Module | Test subset | Statement coverage | One run |
|---|---|---|---|---|
| `ir-builder` | `src/protean/ir/builder.py` | `tests/ir/test_ir_builder.py` and the six `tests/ir/test_*_extraction.py` files (command and event, database model, description, field, handler, index) | 79.5% (1397 of 1757 statements) | 31 min 6 s |
| `ir-diff` | `src/protean/ir/diff.py` | `tests/ir/test_diff.py`, `tests/ir/test_compatibility.py` | 93.2% (618 of 663 statements) | 5 min 1 s |
| `observatory-api` | `src/protean/server/observatory/api.py` | `tests/server/observatory/test_observatory_api.py`, `tests/server/observatory/test_trace_decoding.py` | 88.3% (564 of 639 statements) | 58 s |
| `observatory-timeline` | `src/protean/server/observatory/routes/timeline.py` | `tests/server/observatory/test_observatory_timeline_api.py`, `tests/server/observatory/test_trace_search.py` | 93.7% (445 of 475 statements) | 1 min 45 s |
| `observatory-metrics` | `src/protean/server/observatory/metrics.py` | `tests/server/observatory/test_observatory_metrics.py` | 50.0% (197 of 394 statements) | 3 min 31 s |

The coverage figures were measured in `.venv-mutation` with the commands above,
running the whole subset, and computed from the `Stmts` and `Miss` columns.
The run times are the wall-clock time of one `make mutation` run on a laptop
with an Intel Core i7-1165G7 (4 cores, 8 threads) and 30 GB of RAM, running
Linux.

One file was left out to keep the runs short. Adding
`tests/server/observatory/test_causation_enrichment.py` to
`observatory-timeline` raises its coverage to about 99%. When the extra run
time is worth it, add the file. Then re-measure the counts.

Five facts about mutmut and the `.venv-mutation` environment change the results
for these targets:

- **Decorated functions get no mutants.** mutmut 3 skips any function that
  has a decorator other than `@staticmethod` or `@classmethod`, along with its
  body. The FastAPI route handlers in `api.py` and `timeline.py` carry route
  decorators (`@router.get(...)`, `@router.post(...)`, `@router.delete(...)`).
  mutmut therefore mutates only the module-level helpers those handlers call.
  That is why `observatory-api` produces fewer than 200 mutants from a module
  of over 1,300 lines.
- **The environment installs the `server` and `redis` extras.** The
  Observatory tests import FastAPI, and their test domain configures the Redis
  broker, which needs the `redis` client package. A running Redis server is not
  needed. When a Redis server listens on `127.0.0.1:56379` (the port
  `docker-compose.yml` maps), each test on the shared test domain sends
  `FLUSHDB` to the test broker's database in its teardown. A mutation run then
  wipes that database over and over for as long as it runs. While another test
  run or worktree is using that Redis, do not start a mutation run. The
  `observatory-timeline` tests are marked `no_test_domain`, so that target
  never flushes it.
- **The environment does not install the `telemetry` extra.** Without the
  OpenTelemetry SDK, `metrics.py` serves its hand-written Prometheus text.
- **The OpenTelemetry gauge code is not exercised.**
  `_register_infrastructure_gauges` returns early unless a domain has gone
  through `init_telemetry()` and has a meter provider. The Observatory test
  domain does not enable telemetry, so the function returns early whether or
  not the SDK is installed, and the mutants in it survive. The subset leaves
  out the tests that exercise the function, such as
  `tests/server/test_telemetry_metrics.py`.
- **Redis-marked tests skip.** mutmut passes no `--redis` option, so the 19
  Redis-marked tests in `test_observatory_api.py` and the 13 in
  `test_observatory_metrics.py` do not run. The skipped tests include the
  metrics tests that check the Prometheus output line by line. A mutant that
  only those tests would reach therefore survives.

`observatory-metrics` scores low because of the last two facts above: the
skipped Redis-marked tests and the gauge code that returns early. Of its 1,029
survivors, 414 are in `_hand_rolled_metrics`, which the skipped Redis-marked
tests check. Another 445 are in `_register_infrastructure_gauges`, which
returns early.

Compare a run on a branch with a run on `main` in the same environment. The two
runs then skip the same code, so their counts can be compared.

## Reading the report

The report ends with a score and a list of survivors:

```
MUTATION SCORE: 83.6%  (422/505 killed; 34 lines had no covering test)

SURVIVORS: 83 (inspect one with: ... -m mutmut show <name>)
  protean.utils.outbox.xǁOutboxǁstart_processing__mutmut_1: survived
  ...
```

Mutant names are function-scoped (`…ǁClassǁmethod__mutmut_N`), so `MUT_FILTER`
(a grep pattern on the names) can narrow the printed survivor list to one area.
This helps on a large module where you care about only a few methods. It
filters the report, not the run: mutmut still mutates the whole target module
and runs the full subset. Inspect any single survivor with `mutmut show <name>`
to see the exact change.

For each survivor, decide which of three buckets it falls into:

- **A real gap**: A behaviour that a test should pin but does not. Write the
  test, then re-run to confirm the mutant is now killed. Mutation testing
  exists to find these gaps.
- **An equivalent mutant**: A change that cannot alter observable behaviour, so
  no test can kill it. The classic case in Protean is a `<` to `<=` flip on a
  `datetime.now()` comparison: the two differ only at the exact boundary
  instant, which a wall-clock test can never hit. Only a test that freezes the
  clock to that instant can kill these mutants (see the boundary tests in
  `tests/outbox/test_outbox_aggregate.py`). Such a test is worth writing only
  when the boundary semantics are meaningful.
- **Low value**: Pinning a constant default (for example that a page size is
  exactly 50) is brittle and catches no realistic bug. Skip these deliberately
  rather than writing a test that only restates the literal.

Prefer killing behavioural survivors (wrong comparison, dropped filter,
off-by-one, swapped branch) over cosmetic ones. When you skip a survivor, add a
one-line note on *why* to the PR description. Whoever runs the next pass then
knows the skip was deliberate.

!!! warning "Clear `__pycache__` if you hand-edit the real source to check a mutant"

    `make mutation` is safe here: mutmut mutates a copy under `./mutants/`,
    never the real tree. But if you sanity-check a survivor by editing the real
    source directly (flip the operator, run the test, restore it), clear
    `__pycache__` afterward: `find src tests -name __pycache__ -type d -exec rm
    -rf {} +`. CPython's default `.pyc` validation is timestamp-based (source
    mtime + size). A same-size flip such as `==` to `!=`, restored within the
    same filesystem mtime-second, leaves a `.pyc` whose recorded `(mtime,
    size)` still matches the restored source. Python then keeps running the
    *mutant* bytecode. The symptom is a broad, confusing set of failures (here:
    every sync inline-dispatch test) that vanish the moment you touch the file.
    `git diff` shows nothing.

## Cadence

Run this as a **quarterly pass** on one or two core modules. Each pass raises a
module's score by adding the missing tests, never by lowering a threshold.
`utils/outbox.py` and `core/upcaster.py` have had a full measured pass driven
to completion.

Three code paths now have their own targets: `core/unit_of_work.py` (the
transaction boundary), `utils/sync_dispatch.py` (breadth-first dispatch), and
the checkpoint path in `server/subscription/event_store_subscription.py`. Each
has tests that pin its highest-value behavioural mutants (the sync/async
commit-dispatch guard, the fan-out drain and `None`-context branch, the two
position-write cadence decisions). A good next quarterly pass runs each of
these targets to completion and adds tests for the survivors that remain.
`sync-dispatch` is close to done, while `unit-of-work` and `checkpoint` still
have uncovered regions (partition-key routing, the recovery-checkpoint writer,
`_gap_safe_batch`).

Some survivors in these paths are deliberately left alive because no test can
kill them without restating a literal or freezing the clock to a single instant:

- **The gap-timeout boundary mutant survives** (`_gap_safe_batch`): `now -
  first_seen < gap_timeout_seconds` compares elapsed time on the monotonic
  clock (`time.monotonic()`), so a `<` to `<=` flip differs only at the exact
  timeout instant. In practice that makes it an equivalent mutant, the same
  class as the `datetime.now()` boundaries in the outbox module.
- **Default cadence constants stay untested**: a test that pins the default
  `position_update_interval` or `gap_timeout_seconds` to a specific number
  catches no realistic bug. Tests check the behaviour that matters instead:
  persist *at* the interval, hold *until* the timeout.

## Why a separate Python 3.12 environment

The tool runs in a dedicated `.venv-mutation` at **Python 3.12**, not the
project's Python 3.14, and this is deliberate. Python 3.14 is currently too new
for reliable mutation testing of Protean's compiled dependencies (SQLAlchemy's
C extensions, greenlet, and others). Under 3.14, mutmut's forked workers
segfault on roughly a fifth of mutants, so the results are incomplete. Python
3.12 runs the whole set cleanly. The mutated logic does not depend on the
Python version, so the results represent every supported version. Keeping the
tool in its own environment also means `import protean` never pulls in the
mutation-only dependency for normal development.
