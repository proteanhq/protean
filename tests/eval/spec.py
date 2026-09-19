"""The per-task sidecar spec: the recipe for a task's deterministic gold project.

Each task under ``tasks/<task_id>/`` carries a ``task.md`` (the prompt the
context-driven path sees) and a ``spec.json`` (the structure the gold path
scaffolds). The spec names the project and the aggregate(s) to build; the gold
builder (:mod:`tests.eval.gold`) runs ``protean add aggregate <Name>`` for each
one. Keeping the spec to plain data means adding a task is adding its two files
with no harness edit, so the task set stays declarative.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tests.eval.transcript import TASK_FILE, TASKS_DIRNAME

__all__ = ["SPEC_FILE", "TaskSpec", "list_task_specs", "read_spec"]

SPEC_FILE = "spec.json"


@dataclass(frozen=True)
class TaskSpec:
    """A task's deterministic recipe: the gold project's name and its aggregates.

    ``project_name`` is the package the gold scaffolds under; ``aggregates`` are
    the class names to add to it, one ``protean add aggregate`` each.
    """

    task_id: str
    project_name: str
    aggregates: tuple[str, ...]


def _eval_root() -> Path:
    """The ``tests/eval`` directory, the root for tasks and their specs."""
    return Path(__file__).resolve().parent


def read_spec(task_id: str, *, root: Path | None = None) -> TaskSpec:
    """Load task *task_id*'s :class:`TaskSpec` from its ``spec.json``.

    Raises ``FileNotFoundError`` if the task carries no spec, and ``ValueError``
    if the spec is missing ``project_name`` or names no aggregate: a task the
    gold builder cannot scaffold from is a spec error, not a silent empty build.
    """
    base = root if root is not None else _eval_root()
    path = base / TASKS_DIRNAME / task_id / SPEC_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    project_name = data.get("project_name")
    if not project_name:
        raise ValueError(f"spec for task {task_id!r} has no project_name")
    aggregates = tuple(data.get("aggregates") or ())
    if not aggregates:
        raise ValueError(f"spec for task {task_id!r} names no aggregates")
    return TaskSpec(task_id=task_id, project_name=project_name, aggregates=aggregates)


def list_task_specs(*, root: Path | None = None) -> list[str]:
    """Return the sorted ids of tasks carrying both a ``task.md`` and a
    ``spec.json``.

    A task is scorable only when it has both its prompt and its gold recipe, so
    a directory with one but not the other is skipped. This is the discovery the
    "adding a task needs only its input and expected structure" criterion rests
    on: the comparison finds a task from its files alone.
    """
    base = root if root is not None else _eval_root()
    tasks_dir = base / TASKS_DIRNAME
    if not tasks_dir.is_dir():
        return []
    ids = [
        entry.name
        for entry in tasks_dir.iterdir()
        if entry.is_dir()
        and (entry / TASK_FILE).is_file()
        and (entry / SPEC_FILE).is_file()
    ]
    return sorted(ids)
