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
# The model checks are design-time verification, not a CI gate: run them
# deliberately when a modeled protocol changes, not on every commit. The trace
# validation sections (OCC #1382, checkpoint #1384, recovery #1385) are different:
# they check a
# log of the real code against its spec, so they cannot go stale and are meant to
# run as a per-PR gate.
#
# Requirements: a Java runtime and the TLA+ tools jar. Point at the jar with
#   TLA_TOOLS=/path/to/tla2tools.jar ./check.sh
# Default location is ~/.tla/tla2tools.jar. Download it from
#   https://github.com/tlaplus/tlaplus/releases (tla2tools.jar). The trace
#   validation additionally needs python3 (and `protean` importable to record a
#   fresh trace); it degrades to running the checked-in fixtures otherwise.

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

# --- OCC trace validation (#1382): check the real code against OCC.tla ---------
#
# Unlike the model checks above, these run TLC over a log the *real* Memory /
# SQLAlchemy commit paths emitted, and confirm each recorded step is a behaviour
# OCC.tla permits (see OCCTrace.tla). The conversion needs python3; recording a
# fresh trace additionally needs the `protean` package importable.

REPO_ROOT="$(cd "$SPECS_DIR/.." && pwd)"
PY3="$(command -v python3 || true)"
TDIR="$WORKDIR/trace"

# trace_run <label> <module.tla> <cfg> -> prints the TLC outcome on stdout, one of:
#   pass         no error found
#   temporal     a temporal property was violated (the conform cfg's TraceAccepted)
#   inv:<Name>   the named invariant was violated (e.g. inv:NoConflict)
#   error        TLC did not finish cleanly
# Naming the failed check (as run() does) is what lets a fixture assert the exact
# mechanism it exercises, so a fixture that starts failing for the wrong reason is
# caught rather than counted as a correct rejection.
trace_run() {
    local label="$1" module="$2" cfg="$3" out rc which verdict
    out="$(cd "$TDIR" && java -XX:+UseParallelGC -cp "$JAR" tlc2.TLC \
        -metadir "$WORKDIR/trace-$label" -config "$cfg" "$module" 2>&1)"
    rc=$?
    # Extract a named invariant first. A temporal-property failure can also print
    # "... is violated" (e.g. "Property TraceAccepted is violated"), so match the
    # specific "Invariant <Name>" form and only treat the rest as temporal, rather
    # than letting any "is violated" text be misread as an invariant.
    which="$(printf '%s\n' "$out" \
        | grep -oE "Invariant [A-Za-z0-9_]+ is violated" | head -1 | awk '{print $2}')"
    if [[ $out == *"No error has been found"* ]]; then
        verdict=pass
    elif [[ -n $which ]]; then
        verdict="inv:$which"
    elif [[ $out == *"is violated"* || $out == *"Temporal properties were violated"* ]]; then
        verdict=temporal
    else
        echo error
        return
    fi
    # Cross-check the report against TLC's exit code, as run() does: a clean report
    # with a non-zero exit, or a violation with a zero exit, means TLC did not
    # terminate cleanly, so report error rather than trusting the text.
    if { [[ $verdict == pass ]] && [[ $rc -ne 0 ]]; } \
       || { [[ $verdict != pass ]] && [[ $rc -eq 0 ]]; }; then
        echo error
        return
    fi
    echo "$verdict"
}

# check_trace <converter> <prefix> <conform_cfg> <cover_cfg> <cover_inv> \
#             <label> <log.jsonl> <expect>
# <converter> is the to-tla script, <prefix> the generated module's name prefix,
# and <cover_inv> the invariant the coverage cfg must see violated on a real log
# (OCC: NoConflict; checkpoint: CoverGap). expect is one of:
#   accept          conforms to the spec AND witnesses the covered behaviour
#   reject-conform  fails conformance on TraceAccepted (a seeded divergence)
#   reject-cover    conforms but does not witness the covered behaviour
# Each fixture asserts the exact outcome it was written to produce.
check_trace() {
    local converter="$1" prefix="$2" conform_cfg="$3" cover_cfg="$4" cover_inv="$5"
    local label="$6" jsonl="$7" expect="$8"
    local module="${prefix}_$label"
    if ! "$PY3" "$converter" to-tla \
            --in "$jsonl" --out "$TDIR/$module.tla" >/dev/null 2>&1; then
        echo "  FAIL   trace:$label: could not convert $jsonl to TLA+"
        fail=1
        return
    fi
    local conform cover ok=0 detail
    conform="$(trace_run "$label-conform" "$module.tla" "$conform_cfg")"
    cover="$(trace_run "$label-cover" "$module.tla" "$cover_cfg")"
    if [[ $conform == error || $cover == error ]]; then
        echo "  FAIL   trace:$label: TLC did not finish cleanly (conform=$conform cover=$cover)"
        fail=1
        return
    fi
    case "$expect" in
        accept)
            [[ $conform == pass && $cover == "inv:$cover_inv" ]] && ok=1
            detail="conforms to the spec and witnesses the covered behaviour" ;;
        reject-conform)
            [[ $conform == temporal ]] && ok=1
            detail="correctly rejected -- diverges from the spec (TraceAccepted stalled)" ;;
        reject-cover)
            [[ $conform == pass && $cover == pass ]] && ok=1
            detail="correctly rejected -- covered behaviour not witnessed, under-covered" ;;
    esac
    if [[ $ok -eq 1 ]]; then
        echo "  PASS   trace:$label: $detail"
    else
        echo "  FAIL   trace:$label: expected $expect (conform=$conform cover=$cover)"
        fail=1
    fi
}

# record_trace <converter> <out.jsonl> [extra record args...]: record a fresh trace.
# Exit status distinguishes the two cases the caller treats differently:
#   0  a trace was written
#   1  an interpreter with `protean` was found but the recording errored (a FAIL)
#   3  no interpreter with `protean` is available (a SKIP, like a missing jar)
record_trace() {
    local converter="$1" out="$2"
    shift 2
    if command -v uv >/dev/null 2>&1 \
       && (cd "$REPO_ROOT" && uv run python -c "import protean") >/dev/null 2>&1; then
        (cd "$REPO_ROOT" && uv run python "$converter" \
            record --out "$out" "$@") >/dev/null 2>&1 && return 0
        return 1
    fi
    if [[ -n "$PY3" ]] && "$PY3" -c "import protean" >/dev/null 2>&1; then
        "$PY3" "$converter" record --out "$out" "$@" \
            >/dev/null 2>&1 && return 0
        return 1
    fi
    return 3
}

# --- Recovery trace validation (#1385): check the real code against Recovery.tla -
#
# The recovery analogue of check_trace/record_trace: run TLC over a log the *real*
# EventStoreSubscription recovery path emitted, and confirm each recorded step is a
# behaviour Recovery.tla permits (see RecoveryTrace.tla). Reuses the generic
# trace_run helper above.

# check_recovery_trace <label> <log.jsonl> <expect>
# expect is one of:
#   accept          conforms to Recovery.tla AND witnesses the crash redelivery
#   reject-conform  fails conformance on TraceAccepted (a seeded advance-without-record)
#   reject-cover    conforms but records no crash redelivery, so under-covered
check_recovery_trace() {
    local label="$1" jsonl="$2" expect="$3"
    local module="RecoveryTrace_$label"
    if ! "$PY3" "$SPECS_DIR/recovery_trace.py" to-tla \
            --in "$jsonl" --out "$TDIR/$module.tla" >/dev/null 2>&1; then
        echo "  FAIL   recovery-trace:$label: could not convert $jsonl to TLA+"
        fail=1
        return
    fi
    local conform cover ok=0 detail
    conform="$(trace_run "rec-$label-conform" "$module.tla" RecoveryTrace_conform.cfg)"
    cover="$(trace_run "rec-$label-cover" "$module.tla" RecoveryTrace_cover.cfg)"
    if [[ $conform == error || $cover == error ]]; then
        echo "  FAIL   recovery-trace:$label: TLC did not finish cleanly (conform=$conform cover=$cover)"
        fail=1
        return
    fi
    case "$expect" in
        accept)
            [[ $conform == pass && $cover == "inv:NoRedeliver" ]] && ok=1
            detail="conforms to Recovery.tla and witnesses the crash redelivery" ;;
        reject-conform)
            [[ $conform == temporal ]] && ok=1
            detail="correctly rejected -- diverges from Recovery.tla (TraceAccepted stalled)" ;;
        reject-cover)
            [[ $conform == pass && $cover == pass ]] && ok=1
            detail="correctly rejected -- no crash redelivery, under-covered" ;;
    esac
    if [[ $ok -eq 1 ]]; then
        echo "  PASS   recovery-trace:$label: $detail"
    else
        echo "  FAIL   recovery-trace:$label: expected $expect (conform=$conform cover=$cover)"
        fail=1
    fi
}

# record_recovery_trace <out.jsonl>: record a fresh recovery trace. Same exit-status
# contract as record_trace (0 written, 1 errored, 3 no interpreter with protean).
record_recovery_trace() {
    local out="$1"
    if command -v uv >/dev/null 2>&1 \
       && (cd "$REPO_ROOT" && uv run python -c "import protean") >/dev/null 2>&1; then
        (cd "$REPO_ROOT" && uv run python "$SPECS_DIR/recovery_trace.py" \
            record --out "$out") >/dev/null 2>&1 && return 0
        return 1
    fi
    if [[ -n "$PY3" ]] && "$PY3" -c "import protean" >/dev/null 2>&1; then
        "$PY3" "$SPECS_DIR/recovery_trace.py" record --out "$out" \
            >/dev/null 2>&1 && return 0
        return 1
    fi
    return 3
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
echo "OCC protocol (aggregate optimistic-concurrency no-lost-update, ADR-0013):"
run OCC.tla        OCC.cfg                 pass
run OCC.tla        OCC_bug.cfg             violation  NoLostUpdate
run OCC.tla        OCC_conflict.cfg        violation  NoConflict

echo ""
echo "Recovery protocol (subscription failure-recovery record-before-advance):"
run Recovery.tla   Recovery.cfg            pass
run Recovery.tla   Recovery_bug.cfg        violation  NoDrop
run Recovery.tla   Recovery_dup.cfg        violation  NoRedeliver

echo ""
echo "OCC trace validation (real code vs OCC.tla, #1382):"
if [[ -z "$PY3" ]]; then
    echo "  SKIP   python3 not found; cannot convert OCC logs to TLA+"
else
    mkdir -p "$TDIR"
    cp "$SPECS_DIR/OCC.tla" "$SPECS_DIR/OCCTrace.tla" \
       "$SPECS_DIR/OCCTrace_conform.cfg" "$SPECS_DIR/OCCTrace_cover.cfg" "$TDIR/"
    real="$WORKDIR/occ_real.jsonl"
    record_trace "$SPECS_DIR/occ_trace.py" "$real" --writers 4
    case $? in
        0) check_trace "$SPECS_DIR/occ_trace.py" OCCTrace \
               OCCTrace_conform.cfg OCCTrace_cover.cfg NoConflict \
               real "$real" accept ;;
        3) echo "  SKIP   real trace: no interpreter with 'protean' available to record one" ;;
        *) echo "  FAIL   real trace: 'protean' is importable but recording errored"
           fail=1 ;;
    esac
    # Negative checks (fixtures under specs/traces/): a green run must mean
    # something, so a seeded divergence must fail conformance and an uncontended
    # log must fail coverage. These need only python3 + java, no `protean`.
    check_trace "$SPECS_DIR/occ_trace.py" OCCTrace \
        OCCTrace_conform.cfg OCCTrace_cover.cfg NoConflict \
        bug        "$SPECS_DIR/traces/occ_bug.jsonl"         reject-conform
    check_trace "$SPECS_DIR/occ_trace.py" OCCTrace \
        OCCTrace_conform.cfg OCCTrace_cover.cfg NoConflict \
        noconflict "$SPECS_DIR/traces/occ_no_conflict.jsonl" reject-cover
fi

echo ""
echo "Checkpoint trace validation (real code vs Checkpoint.tla, #1384):"
if [[ -z "$PY3" ]]; then
    echo "  SKIP   python3 not found; cannot convert checkpoint logs to TLA+"
else
    mkdir -p "$TDIR"
    cp "$SPECS_DIR/Checkpoint.tla" "$SPECS_DIR/CheckpointTrace.tla" \
       "$SPECS_DIR/CheckpointTrace_conform.cfg" \
       "$SPECS_DIR/CheckpointTrace_cover.cfg" "$TDIR/"
    ckpt_real="$WORKDIR/checkpoint_real.jsonl"
    record_trace "$SPECS_DIR/checkpoint_trace.py" "$ckpt_real"
    case $? in
        0) check_trace "$SPECS_DIR/checkpoint_trace.py" CheckpointTrace \
               CheckpointTrace_conform.cfg CheckpointTrace_cover.cfg CoverGap \
               real "$ckpt_real" accept ;;
        3) echo "  SKIP   real trace: no interpreter with 'protean' available to record one" ;;
        *) echo "  FAIL   real trace: 'protean' is importable but recording errored"
           fail=1 ;;
    esac
    # Negative checks (fixtures under specs/traces/): a seeded gap-skip divergence
    # must fail conformance and an in-order (gapless) log must fail coverage.
    check_trace "$SPECS_DIR/checkpoint_trace.py" CheckpointTrace \
        CheckpointTrace_conform.cfg CheckpointTrace_cover.cfg CoverGap \
        bug   "$SPECS_DIR/traces/checkpoint_bug.jsonl"    reject-conform
    check_trace "$SPECS_DIR/checkpoint_trace.py" CheckpointTrace \
        CheckpointTrace_conform.cfg CheckpointTrace_cover.cfg CoverGap \
        nogap "$SPECS_DIR/traces/checkpoint_no_gap.jsonl" reject-cover
fi

echo ""
echo "Recovery trace validation (real code vs Recovery.tla, #1385):"
if [[ -z "$PY3" ]]; then
    echo "  SKIP   python3 not found; cannot convert recovery logs to TLA+"
else
    mkdir -p "$TDIR"
    cp "$SPECS_DIR/Recovery.tla" "$SPECS_DIR/RecoveryTrace.tla" \
       "$SPECS_DIR/RecoveryTrace_conform.cfg" "$SPECS_DIR/RecoveryTrace_cover.cfg" \
       "$TDIR/"
    rreal="$WORKDIR/recovery_real.jsonl"
    record_recovery_trace "$rreal"
    case $? in
        0) check_recovery_trace real "$rreal" accept ;;
        3) echo "  SKIP   real trace: no interpreter with 'protean' available to record one" ;;
        *) echo "  FAIL   real trace: 'protean' is importable but recording errored"
           fail=1 ;;
    esac
    # Negative checks (fixtures under specs/traces/): a green run must mean
    # something, so a seeded advance-without-record must fail conformance and a log
    # with no crash redelivery must fail coverage. These need only python3 + java.
    check_recovery_trace divergence "$SPECS_DIR/traces/recovery_divergence.jsonl" \
        reject-conform
    check_recovery_trace nocrash "$SPECS_DIR/traces/recovery_no_crash.jsonl" \
        reject-cover
fi

echo ""
echo "Outbox trace validation (real code vs Outbox.tla, #1383):"
if [[ -z "$PY3" ]]; then
    echo "  SKIP   python3 not found; cannot convert outbox logs to TLA+"
else
    mkdir -p "$TDIR"
    cp "$SPECS_DIR/Outbox.tla" "$SPECS_DIR/OutboxTrace.tla" \
       "$SPECS_DIR/OutboxTrace_conform.cfg" "$SPECS_DIR/OutboxTrace_cover.cfg" \
       "$TDIR/"
    outbox_real="$WORKDIR/outbox_real.jsonl"
    record_trace "$SPECS_DIR/outbox_trace.py" "$outbox_real"
    case $? in
        0) check_trace "$SPECS_DIR/outbox_trace.py" OutboxTrace \
               OutboxTrace_conform.cfg OutboxTrace_cover.cfg NoDuplicateDelivery \
               real "$outbox_real" accept ;;
        3) echo "  SKIP   real trace: no interpreter with 'protean' available to record one" ;;
        *) echo "  FAIL   real trace: 'protean' is importable but recording errored"
           fail=1 ;;
    esac
    # Negative checks (fixtures under specs/traces/): a seeded mark-without-publish
    # must fail conformance and a log with no redelivery must fail coverage. These
    # need only python3 + java.
    check_trace "$SPECS_DIR/outbox_trace.py" OutboxTrace \
        OutboxTrace_conform.cfg OutboxTrace_cover.cfg NoDuplicateDelivery \
        divergence "$SPECS_DIR/traces/outbox_divergence.jsonl" reject-conform
    check_trace "$SPECS_DIR/outbox_trace.py" OutboxTrace \
        OutboxTrace_conform.cfg OutboxTrace_cover.cfg NoDuplicateDelivery \
        noredelivery "$SPECS_DIR/traces/outbox_no_redelivery.jsonl" reject-cover
fi

echo ""
if [[ "$fail" -eq 0 ]]; then
    echo "All checks met their expected outcome."
else
    echo "Some checks did not meet their expected outcome (see above)."
fi
exit "$fail"
