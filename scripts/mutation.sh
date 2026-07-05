#!/usr/bin/env bash
#
# Mutation testing for Protean core (mutmut 3.x).
#
# A *surviving mutant* is a change to Protean source that no test notices — an
# untested (or under-asserted) code path. This script mutates a target module,
# runs a FAST subset of its unit tests against each mutant, and reports the ones
# that survive so they can be turned into tests. Run it as a repeatable
# (quarterly) pass; see docs/community/contributing/mutation-testing.md.
#
# Environment: runs in a DEDICATED Python 3.12 environment at .venv-mutation, not
# the project .venv. Python 3.14 is too bleeding-edge for reliable mutation
# testing of Protean's C-extension dependencies: mutmut 2.x pickle-crashes on it
# and mutmut 3.x segfaults ~20% of mutants (a fork/C-extension interaction).
# Python 3.12 runs cleanly, and the mutated logic is version-independent so the
# results are representative. The project .venv is never touched.
#
# How mutmut 3.x works here: it copies the source tree into a ./mutants/ dir and
# runs tests against the copy, so the real source is never edited in place. We
# copy the whole `src/protean` package (so imports resolve) but restrict mutation
# to the target module via `only_mutate`. Config is a temporary setup.cfg written
# per run and removed afterwards.
#
# Usage:
#   scripts/mutation.sh [target]
#   MUT_FILTER="_run_invariants|_validate_status_transition" scripts/mutation.sh entity
#
# Targets are defined in the case block below. Add one by giving it a module and
# the fast test subset that exercises it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

MVENV="$REPO/.venv-mutation"
MPY="$MVENV/bin/python"
TARGET="${1:-outbox}"

# --- target -> (module to mutate, fast test subset) -----------------------------
case "$TARGET" in
  outbox)
    MODULE="src/protean/utils/outbox.py"
    TESTS="tests/outbox/test_outbox_aggregate.py tests/outbox/test_outbox_repository.py tests/outbox/test_reconciliation.py"
    ;;
  entity)
    MODULE="src/protean/core/entity.py"
    TESTS="tests/field/test_status.py tests/field/test_status_transitions.py tests/entity/invariants tests/value_object/test_vo_invariants.py"
    ;;
  status-field)
    MODULE="src/protean/fields/simple.py"
    TESTS="tests/field/test_status.py tests/field/test_status_transitions.py"
    ;;
  event-sourcing)
    MODULE="src/protean/core/event_sourced_repository.py"
    TESTS="tests/event_sourced_repository tests/event_sourced_aggregates"
    ;;
  repositories-dao)
    MODULE="src/protean/adapters/repository/memory.py"
    TESTS="tests/adapters/repository/memory tests/dao tests/repository"
    ;;
  *)
    echo "Unknown mutation target: '$TARGET'" >&2
    echo "Known targets: outbox, entity, status-field, event-sourcing, repositories-dao" >&2
    exit 2
    ;;
esac

echo ">>> Mutation target: $TARGET"
echo ">>> Mutate:  $MODULE"
echo ">>> Tests:   $TESTS"

# mutmut reads setup.cfg from the repo root; refuse to clobber a real one.
if [ -e "$REPO/setup.cfg" ]; then
  echo "ERROR: $REPO/setup.cfg already exists. This script writes a temporary" >&2
  echo "setup.cfg for mutmut config; move the existing one aside first." >&2
  exit 1
fi

# --- 1. build/refresh the dedicated 3.12 mutation env (leaves .venv alone) -------
echo ">>> Syncing .venv-mutation (Python 3.12)..."
UV_PROJECT_ENVIRONMENT="$MVENV" uv sync --python 3.12 \
  --extra sqlite --group test --group mutation >/dev/null

# --- 2. always clean the working artifacts, even on crash -----------------------
cleanup() { rm -rf "$REPO/mutants" "$REPO/setup.cfg" "$REPO/.mutmut-cache"; }
trap cleanup EXIT
cleanup

# --- 3. write the per-run mutmut config -----------------------------------------
# Copy the whole package (source_paths) so imports resolve, but mutate only the
# target (only_mutate). Test paths go one-per-line (setup.cfg splits on newlines).
{
  echo "[mutmut]"
  echo "source_paths=src/protean"
  echo "only_mutate=$MODULE"
  echo "pytest_add_cli_args_test_selection="
  for t in $TESTS; do echo "    $t"; done
} > "$REPO/setup.cfg"

# --- 4. run mutmut (mutates ./mutants/, not the real source) --------------------
echo ">>> Running mutmut (copies src/protean into ./mutants and runs the subset)..."
LOG="$(mktemp)"
"$MPY" -m mutmut run 2>&1 | tee "$LOG" | grep -vE "^(src/|mutants/|/)" || true

# --- 5. report ------------------------------------------------------------------
echo ""
echo "================ MUTATION REPORT: $TARGET ================"
"$MPY" - "$LOG" <<'PYEOF'
import re
import sys

data = open(sys.argv[1], encoding="utf-8", errors="replace").read()

def last(emoji):
    vals = re.findall(emoji + r"\s*(\d+)", data)
    return int(vals[-1]) if vals else 0

killed = last("🎉")
not_covered = last("🫥")
timeout = last("⏰")
suspicious = last("🤔")
survived = last("🙁")
skipped = last("🔇")
# Score = killed / (mutants a covering test actually exercised).
tested = killed + survived + timeout + suspicious
score = (killed / tested * 100) if tested else 0.0
print(f"killed={killed}  survived={survived}  timeout={timeout}  "
      f"suspicious={suspicious}  not-covered={not_covered}  skipped={skipped}")
print(f"MUTATION SCORE: {score:.1f}%  ({killed}/{tested} killed; "
      f"{not_covered} lines had no covering test)")
PYEOF

# List survivors (optionally filtered by MUT_FILTER, a grep pattern on the mutant
# name — mutant names are function-scoped, e.g. ...ǁOutboxǁstart_processing__mutmut_3).
echo ""
FILTER="${MUT_FILTER:-.}"
SURV="$("$MPY" -m mutmut results 2>/dev/null | sed 's/^ *//' | grep -E ': survived$' | grep -E "$FILTER" || true)"
COUNT="$(printf '%s\n' "$SURV" | grep -c ':' || true)"
if [ -n "${MUT_FILTER:-}" ]; then
  echo "SURVIVORS matching /$MUT_FILTER/: $COUNT"
else
  echo "SURVIVORS: $COUNT (inspect one with: $MPY -m mutmut show <name>)"
fi
printf '%s\n' "$SURV" | sed 's/^/  /'
echo "========================================================="
