"""The generation-gap seam works against the real element model (ADR-0035).

This proves the two-file base/subclass split is not just a file-layout idea: the
generated base and the hand-owned subclass compose into a valid
``@domain.aggregate``. A real ``domain.init(traverse=True)`` loads them, pydantic
validation works, and an invariant declared in the subclass fires.

The re-run tests exercise the seam's rule through the local ``_apply`` helper.
``add`` still only previews; the applier that honors ``ownership`` on disk arrives
in a later issue (ADR-0035). ``_apply`` models exactly the rule that applier will
follow, so these tests fix the contract the applier has to meet.

The aggregate is exercised by ``project_checks/test_generation_gap.py``, which
runs with pytest in a child interpreter inside the project, the way a user's
project runs it. Module discovery and registration happen in a clean interpreter
rather than being tangled up with the test process's already-imported modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.scaffold import (
    OWNERSHIP_HAND_OWNED,
    ChangePlan,
    CreateFileOperation,
    plan_add_slice,
)
from tests.support.project_tests import passed_count, run_tests_in

pytestmark = pytest.mark.no_test_domain

_CHECKS = Path(__file__).parent / "project_checks"

# The developer's edit to the hand-owned subclass: an invariant plus a sentinel
# the re-run test looks for to prove the file survived untouched. This is the
# code a re-run of ``add`` must never overwrite.
_HAND_EDITED_AGGREGATE = (_CHECKS / "order_aggregate.py").read_text(encoding="utf-8")
SENTINEL = "developer-owned-marker-4c1f"


def _scaffold_project(root: Path) -> Path:
    """Lay down a minimal canonical project (``src/myproj/domain.py``) and return
    the project root, ready for the planned slice to be applied into it."""
    package = root / "src" / "myproj"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "domain.py").write_text(
        "from protean.domain import Domain\n\nmyproj = Domain(name='myproj')\n",
        encoding="utf-8",
    )
    return root


def _apply(plan: ChangePlan, root: Path) -> None:
    """Materialise a plan on disk with the seam's re-run rule (ADR-0035): a
    ``generated`` file is always (re)written, a ``hand_owned`` file is written
    only if it does not already exist. This is the rule the future applier will
    follow; here it drives the verification."""
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        target = root / op.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and op.ownership == OWNERSHIP_HAND_OWNED:
            continue
        target.write_text(op.content, encoding="utf-8")


def _run_checks(project: Path) -> None:
    """Run ``project_checks/test_generation_gap.py`` in *project* and require
    every test in it to pass."""
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    result = run_tests_in(project, [_CHECKS / "test_generation_gap.py"])

    assert result.returncode == 0, (
        f"the seam did not compose into a working aggregate:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert passed_count(result) == 5, result.stdout


def test_base_and_subclass_compose_into_a_valid_aggregate(tmp_path):
    """Acceptance: the generated base and the hand-owned subclass load, validate,
    and run a subclass invariant under a real ``domain.init(traverse=True)``."""
    project = _scaffold_project(tmp_path / "proj")

    plan = plan_add_slice(str(project), "aggregate", "Order")
    _apply(plan, project)
    # The developer fills in the hand-owned subclass with an invariant.
    (project / "src/myproj/order/aggregate.py").write_text(
        _HAND_EDITED_AGGREGATE, encoding="utf-8"
    )

    _run_checks(project)


def test_rerun_refreshes_the_base_and_preserves_the_hand_owned_subclass(tmp_path):
    """Acceptance: after the developer edits the hand-owned subclass, re-running
    the seam (re-plan, then apply with the ownership rule) refreshes the generated
    base and leaves the subclass untouched.

    This is the issue's core scenario: add, edit the hand-owned side, re-add; the
    hand edit is preserved and the generated side is refreshed. The apply step is
    the local ``_apply`` helper, which models the rule the future applier follows.
    """
    project = _scaffold_project(tmp_path / "proj")
    base_path = project / "src/myproj/order/aggregate_base.py"
    aggregate_path = project / "src/myproj/order/aggregate.py"

    # First apply, then the developer edits the hand-owned subclass.
    first_plan = plan_add_slice(str(project), "aggregate", "Order")
    _apply(first_plan, project)
    aggregate_path.write_text(_HAND_EDITED_AGGREGATE, encoding="utf-8")

    generated_base = base_path.read_text(encoding="utf-8")
    # Simulate the base drifting since the first run (a stale generated file). A
    # correct re-run must overwrite this back to the generated content.
    base_path.write_text("# stale, must be refreshed\n", encoding="utf-8")

    # Re-run: plan the same slice again and apply with the seam's rule.
    second_plan = plan_add_slice(str(project), "aggregate", "Order")
    _apply(second_plan, project)

    # The generated base was refreshed (the stale content is gone, the generated
    # content is back).
    refreshed_base = base_path.read_text(encoding="utf-8")
    assert refreshed_base == generated_base
    assert "stale, must be refreshed" not in refreshed_base

    # The hand-owned subclass was preserved verbatim: the developer's invariant
    # and sentinel are still there.
    preserved = aggregate_path.read_text(encoding="utf-8")
    assert preserved == _HAND_EDITED_AGGREGATE
    assert SENTINEL in preserved
    assert "name_must_not_be_blank" in preserved

    # And the refreshed base + preserved subclass still compose and run.
    _run_checks(project)
