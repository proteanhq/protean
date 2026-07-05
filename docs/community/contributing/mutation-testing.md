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

`make mutation` delegates to [`scripts/mutation.sh`](https://github.com/proteanhq/protean/blob/main/scripts/mutation.sh),
which:

1. Builds a dedicated Python 3.12 environment at `.venv-mutation` (see the
   caveat below). The project `.venv` is never touched.
2. Mutates the target module and runs a **fast subset** of its unit tests
   against each mutant, not the whole suite. A per-module subset keeps a run to
   a few minutes.
3. Prints a mutation score and the list of surviving mutants.

It uses [mutmut](https://github.com/boxed/mutmut) 3.x, which copies the source
tree into a `./mutants/` directory and runs the tests against the copy — so the
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

Mutant names are function-scoped (`…ǁClassǁmethod__mutmut_N`), so you can focus a
run on one area with `MUT_FILTER` (a grep pattern on the names) and inspect any
single mutant with `mutmut show <name>` to see the exact change.

For each survivor, decide which of three buckets it falls into:

- **A real gap.** A behaviour that a test should pin but does not. Write the
  test, then re-run to confirm the mutant is now killed. This is the whole point
  of the exercise.
- **An equivalent mutant.** A change that cannot alter observable behaviour, so
  no test can kill it. The classic case in Protean is a `<` to `<=` flip on a
  `datetime.now()` comparison: the two differ only at the exact boundary
  instant, which a wall-clock test can never hit. These are killable only by
  freezing the clock to that instant (see the boundary tests in
  `tests/outbox/test_outbox_aggregate.py`), and are worth a test only when the
  boundary semantics are meaningful.
- **Low value.** Pinning a constant default (for example that a page size is
  exactly 50) is brittle and catches no realistic bug. Skip these deliberately
  rather than writing a test that only restates the literal.

Prefer killing behavioural survivors (wrong comparison, dropped filter,
off-by-one, swapped branch) over cosmetic ones. When you skip a survivor, a
one-line note in the PR description on *why* keeps the next pass honest.

## Cadence

Treat this as a **quarterly pass**: pick one or two core modules, drive their
score up by adding the missing tests, and land the tests (never a lowered
threshold). Modules already hardened this way include `utils/outbox.py`.

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
