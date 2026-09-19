"""The per-task sidecar spec: the recipe for a task's deterministic gold project.

Each task under ``tasks/<task_id>/`` carries a ``task.md`` (the prompt the
context-driven path sees) and a ``spec.json`` (the structure the gold path
scaffolds). The spec names the project and the aggregate(s) to build; the gold
builder (:mod:`tests.eval.gold`) runs ``protean add aggregate <Name>`` for each
one. Keeping the spec to plain data means adding a task is adding its two files
with no harness edit, so the task set stays declarative.

A spec names its aggregates in one of two forms: a flat ``aggregates`` list, or a
nested ``contexts`` object mapping each context to its aggregates. Both reduce to
the same flat aggregate list the gold builder scaffolds; the nested form also
declares which context each aggregate is expected to land in, and ``read_spec``
checks that declaration against what the gold builder will actually build. A
spec uses one form or the other, never both: naming ``aggregates`` alongside
``contexts`` is a read error rather than a list that is silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from protean.scaffold.slice_generator import split_words
from tests.eval.transcript import TASK_FILE, TASKS_DIRNAME

__all__ = ["SPEC_FILE", "TaskSpec", "list_task_specs", "read_spec"]

SPEC_FILE = "spec.json"


@dataclass(frozen=True)
class TaskSpec:
    """A task's deterministic recipe: the gold project's name and its aggregates.

    ``project_name`` is the package the gold scaffolds under; ``aggregates`` are
    the class names to add to it, one ``protean add aggregate`` each. Both
    ``aggregates`` and the names inside ``contexts`` hold the class name the
    scaffold emits, so a spec that writes an alias such as ``orderItem`` is read
    back as the ``OrderItem`` the gold project will carry (see
    :func:`_class_name`).

    ``contexts`` is the optional bounded-context grouping a multi-context task
    declares: ``(context_name, aggregate_class_names)`` pairs. It states which
    context each aggregate belongs to as data, rather than leaving it implicit in
    the aggregate name. The flat ``aggregates`` tuple is always the union of the
    contexts' aggregates in declaration order, so the gold builder reads only
    ``aggregates`` and does not care which form the spec used. A flat spec (one
    that names ``aggregates`` directly) leaves ``contexts`` empty and makes no
    context claim; each of its aggregates still lands in its own context module.
    """

    task_id: str
    project_name: str
    aggregates: tuple[str, ...]
    contexts: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _class_name(aggregate: str) -> str:
    """The class name ``protean add aggregate`` emits for *aggregate*.

    The scaffold normalizes its name argument, so ``order``, ``orderItem`` and
    ``order_item`` build the classes ``Order`` and ``OrderItem``. The spec stores
    the normalized name because that is what the gold's IR carries, and the
    scorer looks the spec's declared context up by the IR's class name: a spec
    keeping the raw alias would find no declaration for ``Order`` and leave the
    task's layout unscored.
    """
    return "".join(word[:1].upper() + word[1:] for word in split_words(aggregate))


def _slug(aggregate: str) -> str:
    """The slice module ``protean add aggregate`` builds for *aggregate*.

    The same snake_case derivation the scaffold uses, so ``Order`` lands in
    ``order`` and ``OrderItem`` in ``order_item``.
    """
    return "_".join(word.lower() for word in split_words(aggregate))


def _read_contexts(
    task_id: str, contexts_data: object
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Read and check the ``contexts`` object of task *task_id*'s spec.

    Every failure raises ``ValueError`` at read time, so a spec the gold builder
    cannot honour never gets as far as scaffolding a project whose contexts do
    not match what the spec declared. The checks are:

    - ``contexts`` must be a JSON object. Any other value, including a falsey one
      such as ``[]``, ``""`` or ``null``, is a malformed spec, not an absent
      field: ``read_spec`` branches on the key being present, so a written
      ``null`` reaches this check rather than reading as no contexts at all.
    - each context must name a list of non-empty strings. A bare string such as
      ``{"sales": "Order"}`` would otherwise iterate into one-character aggregate
      names.
    - each context must name exactly one aggregate, whose slug is the context
      name. ``protean add aggregate <Name>`` is the only shape the gold builder
      has, and it puts each aggregate in its own slice module named after the
      aggregate, so a context declaring ``["Order", "Cart"]`` would be built as
      the two contexts ``order`` and ``cart``, not as the declared one.

    The slug is taken from the class name, not from the raw spec text, because
    the gold builder scaffolds from the class name this function stores. The two
    can differ: ``aB`` slugs to ``a_b`` on its own, but the class it emits,
    ``AB``, slugs to ``ab``. Checking the raw name would accept
    ``{"a_b": ["aB"]}`` and then build the context ``ab``, so the gold would miss
    its own declared context.
    """
    if not isinstance(contexts_data, dict):
        raise ValueError(f"spec for task {task_id!r} has a non-object contexts field")
    contexts: list[tuple[str, tuple[str, ...]]] = []
    for name, members in contexts_data.items():
        context = str(name)
        if not isinstance(members, list) or not all(
            isinstance(member, str) and member for member in members
        ):
            raise ValueError(
                f"spec for task {task_id!r} declares context {context!r} as "
                f"{members!r}; a context must name a list of aggregate names"
            )
        classes = [_class_name(member) for member in members]
        slugs = [_slug(name) for name in classes]
        if slugs != [context]:
            built = ", ".join(slugs) or "nothing"
            raise ValueError(
                f"spec for task {task_id!r} declares context {context!r} with "
                f"aggregates {list(members)!r}, which the gold builds as {built}: "
                "`protean add aggregate` puts every aggregate in its own slice "
                "module, named after the class it emits, so a context must name "
                "the one aggregate whose class slugs to the context name"
            )
        contexts.append((context, tuple(classes)))
    return tuple(contexts)


def _eval_root() -> Path:
    """The ``tests/eval`` directory, the root for tasks and their specs."""
    return Path(__file__).resolve().parent


def read_spec(task_id: str, *, root: Path | None = None) -> TaskSpec:
    """Load task *task_id*'s :class:`TaskSpec` from its ``spec.json``.

    Raises ``FileNotFoundError`` if the task carries no spec, and ``ValueError``
    if the spec is missing ``project_name``, names no aggregate, names both
    ``contexts`` and ``aggregates``, or declares a ``contexts`` grouping the gold
    builder cannot build (see :func:`_read_contexts`). This way a task the gold
    builder cannot scaffold from, or would scaffold into contexts other than the
    declared ones, fails loudly at read time.
    """
    base = root if root is not None else _eval_root()
    path = base / TASKS_DIRNAME / task_id / SPEC_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    project_name = data.get("project_name")
    if not project_name:
        raise ValueError(f"spec for task {task_id!r} has no project_name")

    # Branch on the key being there, not on its value: a spec that writes
    # ``"contexts": null`` supplied the field, so it is a malformed contexts
    # object for :func:`_read_contexts` to reject, not an absent one that falls
    # back to the flat ``aggregates`` list.
    if "contexts" in data:
        contexts = _read_contexts(task_id, data["contexts"])
        # After the contexts object itself is checked, so a spec that is
        # malformed as well as contradictory is reported as malformed first.
        if "aggregates" in data:
            raise ValueError(
                f"spec for task {task_id!r} names both contexts and aggregates; "
                "the two are alternative forms of the same list, so a spec must "
                "use one or the other"
            )
        aggregates = tuple(
            aggregate for _, members in contexts for aggregate in members
        )
    else:
        contexts = ()
        aggregates = tuple(
            _class_name(aggregate) if isinstance(aggregate, str) else aggregate
            for aggregate in data.get("aggregates") or ()
        )

    if not aggregates:
        raise ValueError(f"spec for task {task_id!r} names no aggregates")
    return TaskSpec(
        task_id=task_id,
        project_name=project_name,
        aggregates=aggregates,
        contexts=contexts,
    )


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
