#!/usr/bin/env bash
#
# Model-check the Protean protocol specs with TLC.
#
# Runs every configuration and asserts the expected outcome:
#   - the shipped-protocol configs MUST pass (no invariant or liveness violation);
#   - the revert-test configs (…_bug, …_claim) MUST fail on a NAMED invariant
#     (they reintroduce a real bug, so a passing run, or a failure on a different
#     invariant, means the check no longer demonstrates that bug);
#   - the reachability probes (…_dup) MUST fail on their named invariant (the
#     counterexample is the witness that the behavior is reachable).
#
# This is design-time verification, not a CI gate: run it deliberately when a
# modeled protocol changes, not on every commit.
#
# Requirements: a Java runtime and the TLA+ tools jar. Point at the jar with
#   TLA_TOOLS=/path/to/tla2tools.jar ./check.sh
# Default location is ~/.tla/tla2tools.jar. Download it from
#   https://github.com/tlaplus/tlaplus/releases (tla2tools.jar).

set -uo pipefail

SPECS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAR="${TLA_TOOLS:-$HOME/.tla/tla2tools.jar}"

# Probe that java actually RUNS. `command -v java` is not enough: macOS ships a
# /usr/bin/java stub that exists on PATH but errors "Unable to locate a Java
# Runtime" when no JDK is installed.
if ! java -version >/dev/null 2>&1; then
    echo "error: no working Java runtime ('java -version' failed)." >&2
    echo "       Install a JDK, e.g. 'brew install openjdk'." >&2
    exit 2
fi
if [[ ! -f "$JAR" ]]; then
    echo "error: TLA+ tools jar not found at '$JAR'." >&2
    echo "       Download tla2tools.jar from https://github.com/tlaplus/tlaplus/releases" >&2
    echo "       and set TLA_TOOLS to its path." >&2
    exit 2
fi

fail=0

# TLC writes state-graph scratch files; keep them out of the source tree, and
# give each run its own subdir so no stale checkpoint is carried between runs.
# The explicit template keeps this portable across GNU and BSD/macOS mktemp.
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/protean-specs.XXXXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

# run <module.tla> <config.cfg> <expect: pass|violation> [expected-invariant]
run() {
    local module="$1" cfg="$2" expect="$3" expectInv="${4:-}"
    local out rc passed violated which
    out="$(cd "$SPECS_DIR" && java -XX:+UseParallelGC -cp "$JAR" tlc2.TLC \
        -metadir "$WORKDIR/${cfg%.cfg}" -config "$cfg" "$module" 2>&1)"
    rc=$?

    # Classify from the report text (in-process, so no pipe/SIGPIPE fragility)
    # and cross-check against TLC's exit code.
    passed=0; violated=0
    [[ $out == *"No error has been found"* ]] && passed=1
    [[ $out == *"is violated"* || $out == *"Temporal properties were violated"* ]] \
        && violated=1

    if { [[ $passed -eq 1 ]] && [[ $rc -ne 0 ]]; } \
       || { [[ $violated -eq 1 ]] && [[ $rc -eq 0 ]]; }; then
        echo "  FAIL   $cfg: TLC's report and exit code disagree (rc=$rc)"
        fail=1; return
    fi

    if [[ $passed -eq 1 ]]; then
        if [[ $expect == "pass" ]]; then
            echo "  PASS   $cfg: all checks hold"
        else
            echo "  FAIL   $cfg: expected a violation but TLC found none (model lost its teeth)"
            fail=1
        fi
    elif [[ $violated -eq 1 ]]; then
        which="$(printf '%s\n' "$out" \
            | grep -oE "Invariant [A-Za-z0-9_]+ is violated" | head -1 | awk '{print $2}')"
        if [[ $expect != "violation" ]]; then
            echo "  FAIL   $cfg: unexpected violation (${which:-a property})"
            fail=1
        elif [[ -n $expectInv && ${which:-} != "$expectInv" ]]; then
            echo "  FAIL   $cfg: expected $expectInv to fail, got ${which:-a property} (unrelated regression?)"
            fail=1
        else
            echo "  PASS   $cfg: TLC produced the expected counterexample (${which:-property})"
        fi
    else
        echo "  FAIL   $cfg: TLC did not finish cleanly (rc=$rc):"
        printf '%s\n' "$out" | tail -3 | sed 's/^/           /'
        fail=1
    fi
}

echo "Checkpoint protocol (\$all gap-safe checkpointing, ADR-0025):"
run Checkpoint.tla Checkpoint.cfg          pass
run Checkpoint.tla Checkpoint_timeout.cfg  pass
run Checkpoint.tla Checkpoint_bug.cfg      violation  NoSkip
run Checkpoint.tla Checkpoint_dup.cfg      violation  NoRedelivery

echo ""
echo "Outbox protocol (transactional two-phase publish, ADR-0013 claim):"
run Outbox.tla     Outbox.cfg              pass
run Outbox.tla     Outbox_bug.cfg          violation  PublishedImpliesDelivered
run Outbox.tla     Outbox_claim.cfg        violation  NoDoubleActiveClaim
run Outbox.tla     Outbox_dup.cfg          violation  NoDuplicateDelivery

echo ""
if [[ "$fail" -eq 0 ]]; then
    echo "All checks met their expected outcome."
else
    echo "Some checks did not meet their expected outcome (see above)."
fi
exit "$fail"
