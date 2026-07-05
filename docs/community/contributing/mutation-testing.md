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
MUT_LINES="645-690,749-802" make mutation TARGET=entity   # filter the report
```

`make mutation` delegates to [`scripts/mutation.sh`](https://github.com/proteanhq/protean/blob/main/scripts/mutation.sh),
which:

1. Builds a dedicated Python 3.12 environment at `.venv-mutation` (see the
   caveat below). The project `.venv` is never touched.
2. Mutates the target module and runs a **fast subset** of its unit tests
   against each mutant, not the whole suite. A per-module subset keeps a run to
   a few minutes.
3. Prints a mutation score and the list of surviving mutants, read straight from
   the `.mutmut-cache` SQLite database.

A run mutates the source file in place and restores it afterwards; the script
keeps a backup and restores unconditionally, so an interrupted run still leaves
the working tree clean.

### Adding a target

Targets live in a `case` block in `scripts/mutation.sh`. Each maps a name to a
source module and the fast test subset that exercises it. Pick the smallest set
of tests that covers the module's behaviour; a broad subset only slows the run
without finding more survivors.

## Reading the report

The report ends with a score and a list of survivors:

```
MUTATION SCORE: 94.9%  (278/293 mutants killed)

SURVIVORS: 3
  src/protean/utils/outbox.py:203:  if current_time < ensure_utc_aware(self.next_retry_at):
  ...
```

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

## Environment caveats

Two quirks are handled by the script so you do not have to, but they are worth
knowing if you invoke `mutmut` directly:

- **Python version.** `mutmut` 2.x crashes on Python 3.14 (a
  `cannot pickle 'itertools.count'` error) and records nothing. The script
  therefore builds `.venv-mutation` at Python 3.12, which is within Protean's
  supported range. The mutation results are representative of every supported
  version because the mutated logic is version independent.
- **Reading results.** `mutmut results` and `mutmut show` crash on the resolved
  `pony-orm` ("QueryResultIterator not iterable"). The script reads survivors
  directly from the `.mutmut-cache` SQLite file instead:

    ```sql
    select L.line_number, L.line
    from Mutant M join Line L on M.line = L.id
    where M.status = 'bad_survived'
    order by L.line_number;
    ```
