#!/usr/bin/env bash
#
# Mutation testing for Protean core.
#
# A *surviving mutant* is a change to Protean source that no test notices — an
# untested (or under-asserted) code path. This script mutates a target module,
# runs a FAST subset of its unit tests against each mutant, and reports the ones
# that survive so they can be turned into tests. Run it as a repeatable
# (quarterly) pass; see docs/community/contributing/mutation-testing.md.
#
# Two environment quirks are handled here so callers don't have to:
#
#   1. mutmut 2.x crashes on Python 3.14 ("cannot pickle 'itertools.count'"), and
#      the project .venv is 3.14. So the tool runs in a DEDICATED environment at
#      .venv-mutation, built at Python 3.12. The project .venv is never touched.
#   2. `mutmut results` / `mutmut show` crash on the resolved pony-orm
#      ("QueryResultIterator not iterable"), so survivors are read straight from
#      the .mutmut-cache SQLite database instead of via the mutmut CLI.
#
# Usage:
#   scripts/mutation.sh [target]
#   MUT_LINES="645-690,755-800" scripts/mutation.sh entity   # filter report to ranges
#
# Targets are defined in the case block below. Add a new one by giving it a
# source path and the fast test subset that exercises it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

MVENV="$REPO/.venv-mutation"
MPY="$MVENV/bin/python"
TARGET="${1:-outbox}"

# --- target -> (source module, fast test subset) --------------------------------
case "$TARGET" in
  outbox)
    SRC="src/protean/utils/outbox.py"
    TESTS="tests/outbox/test_outbox_aggregate.py tests/outbox/test_outbox_repository.py tests/outbox/test_reconciliation.py"
    ;;
  entity)
    SRC="src/protean/core/entity.py"
    TESTS="tests/field/test_status.py tests/field/test_status_transitions.py tests/entity/invariants tests/value_object/test_vo_invariants.py"
    ;;
  status-field)
    SRC="src/protean/fields/simple.py"
    TESTS="tests/field/test_status.py tests/field/test_status_transitions.py"
    ;;
  *)
    echo "Unknown mutation target: '$TARGET'" >&2
    echo "Known targets: outbox, entity, status-field" >&2
    exit 2
    ;;
esac

echo ">>> Mutation target: $TARGET"
echo ">>> Source:  $SRC"
echo ">>> Tests:   $TESTS"

# --- 1. build/refresh the dedicated 3.12 mutation env (leaves .venv alone) -------
echo ">>> Syncing .venv-mutation (Python 3.12)..."
UV_PROJECT_ENVIRONMENT="$MVENV" uv sync --python 3.12 \
  --extra sqlite --group test --group mutation >/dev/null

# --- 2. safety net: mutmut edits SRC in place; guarantee we restore it -----------
BAK="$(mktemp)"
cp "$SRC" "$BAK"
restore_src() {
  # Restore the pristine source unconditionally, even if mutmut is killed
  # mid-mutant and leaves a mutation on disk.
  cp "$BAK" "$SRC"
  rm -f "$BAK"
}
trap restore_src EXIT

# --- 3. run mutmut ---------------------------------------------------------------
rm -f "$REPO/.mutmut-cache"
echo ">>> Running mutmut (this mutates $SRC and runs the subset per mutant)..."
# mutmut exits non-zero when survivors remain; that's expected, so don't let
# `set -e` abort before we print the report.
"$MPY" -m mutmut run \
  --paths-to-mutate "$SRC" \
  --tests-dir tests/ \
  --runner "$MPY -m pytest $TESTS -x -q -p no:cacheprovider" || true

# --- 4. report from the SQLite cache (CLI is broken on pony-orm) -----------------
echo ""
echo "================ MUTATION REPORT: $TARGET ================"
MUT_LINES="${MUT_LINES:-}" "$MPY" - "$SRC" <<'PYEOF'
import os
import sqlite3
import sys

src = sys.argv[1]

# mutmut may have crashed before writing a usable cache. Fail loudly with a
# clear message instead of a confusing "no such table: Mutant" (or an empty DB
# silently created by sqlite3.connect).
if not os.path.exists(".mutmut-cache"):
    sys.exit("ERROR: .mutmut-cache not found — `mutmut run` produced no results "
             "(it likely crashed before recording any mutants).")
con = sqlite3.connect(".mutmut-cache")
has_mutant_table = con.execute(
    "select count(*) from sqlite_master where type='table' and name='Mutant'"
).fetchone()[0]
if not has_mutant_table:
    sys.exit("ERROR: .mutmut-cache has no 'Mutant' table — `mutmut run` did not "
             "record any results (crash, or an incompatible cache schema).")

counts = dict(con.execute("select status, count(*) from Mutant group by status").fetchall())
killed = counts.get("ok_killed", 0)
survived = counts.get("bad_survived", 0)
timeout = counts.get("bad_timeout", 0)
suspicious = counts.get("ok_suspicious", 0)
skipped = counts.get("skipped", 0)
# "killed" for scoring = anything the suite reacted to (killed/timeout/suspicious).
reacted = killed + timeout + suspicious
tested = reacted + survived
score = (reacted / tested * 100) if tested else 0.0

print(f"killed={killed}  survived={survived}  timeout={timeout}  "
      f"suspicious={suspicious}  skipped={skipped}")
print(f"MUTATION SCORE: {score:.1f}%  ({reacted}/{tested} mutants killed)")

# Optional line-range filter for large files: MUT_LINES="645-690,755-800"
ranges = []
spec = os.environ.get("MUT_LINES", "").strip()
for part in filter(None, (p.strip() for p in spec.split(","))):
    lo, _, hi = part.partition("-")
    ranges.append((int(lo), int(hi or lo)))

def in_range(n):
    return not ranges or any(lo <= n <= hi for lo, hi in ranges)

rows = con.execute(
    "select L.line_number, L.line from Mutant M join Line L on M.line = L.id "
    "where M.status = 'bad_survived' order by L.line_number"
).fetchall()
shown = [(n, t) for (n, t) in rows if in_range(n)]

hdr = "SURVIVORS" + (f" (lines {spec})" if ranges else "")
print(f"\n{hdr}: {len(shown)}" + (f" of {len(rows)} total" if ranges else ""))
for n, text in shown:
    print(f"  {src}:{n}:  {text.strip()}")
PYEOF
echo "========================================================="
