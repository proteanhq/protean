"""Tests for ``protean add``: it previews a create-only aggregate slice, writes
nothing, and the slice it plans actually registers under traversal.

The traversal-load test is the sharp edge (issue acceptance #3): a slice that is
placed wrong, or whose ``__init__.py`` is not side-effect free, or whose imports
do not resolve, makes ``init(traverse=True)`` crash or silently under-discover.
Here we materialize the planned files into a real generated project and assert the
registry holds the new elements after init.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.scaffold import CreateFileOperation
from protean.scaffold.add_plan import plan_add_slice

# These generate and start their own projects; the autouse domain fixture would
# build an unrelated Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain

_PACKAGE = "scaffolded"


def _generate(tmp_path: Path, name: str = _PACKAGE) -> Path:
    """Run ``protean new`` and return the generated project root."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    result = CliRunner().invoke(
        app,
        ["new", name, "-o", str(out), "--defaults", "--skip-setup"],
    )
    assert result.exit_code == 0, f"protean new failed: {result.output}"
    return out / name


def _snapshot(root: Path) -> dict[str, bytes]:
    """Map every file under *root* to its bytes, for a before/after compare."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _materialize(project: Path, plan) -> None:
    """Write a plan's create operations into *project*, as apply would."""
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        target = project / op.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op.content)


def _subprocess_env(project: Path) -> dict[str, str]:
    """Env for running the generated project uninstalled (its ``src/`` on the
    path, and the leak-prone vars dropped). Mirrors the working-project test."""
    src = str(project / "src")
    existing = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": src + os.pathsep + existing if existing else src,
    }
    env.pop("VIRTUAL_ENV", None)
    env.pop("PROTEAN_ENV", None)
    env.pop("PROTEAN_DEBUG", None)
    return env


_INIT_AND_EXERCISE = (
    "import sys; sys.path.insert(0, 'src')\n"
    "from scaffolded.domain import scaffolded as domain\n"
    "domain.init()\n"
    "names = sorted(domain.registry._elements_by_name.keys())\n"
    "print('NAMES:' + ','.join(names))\n"
    # Drive the slice end to end: process the command through the generated
    # handler (which calls the generated `create` factory), then fetch the
    # persisted aggregate back. command_processing is sync in the scaffold, so
    # process runs the handler inline and returns the aggregate id.
    "from scaffolded.order.commands import CreateOrder\n"
    "from scaffolded.order.aggregate import Order\n"
    "with domain.domain_context():\n"
    "    order_id = domain.process(CreateOrder(name='Widget'))\n"
    "    fetched = domain.repository_for(Order).get(order_id)\n"
    "    print('PERSISTED:' + fetched.name)\n"
)


def test_add_previews_the_five_create_operations(tmp_path):
    project = _generate(tmp_path)

    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project)]
    )

    assert result.exit_code == 0, result.output
    for path in (
        "src/scaffolded/order/__init__.py",
        "src/scaffolded/order/aggregate.py",
        "src/scaffolded/order/commands.py",
        "src/scaffolded/order/events.py",
        "src/scaffolded/order/command_handlers.py",
    ):
        assert f"create {path}" in result.output, (
            f"preview did not name a create for {path}:\n{result.output}"
        )


def test_add_writes_nothing(tmp_path):
    project = _generate(tmp_path)

    before = _snapshot(project)
    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project)]
    )
    after = _snapshot(project)

    assert result.exit_code == 0, result.output
    assert before == after, "protean add must not touch the project tree"


def test_planned_slice_loads_and_registers_under_traversal(tmp_path):
    """Acceptance #3: the planned files register when the domain inits with
    traversal on, and the slice actually works. Materialize the plan, init the
    real domain, require all four elements in the registry by name, then process a
    command through the generated handler and assert the aggregate persists.

    Asserting only the registry names is not enough: a broken `create` factory or
    a handler missing its decorator can still leave the names present. Running the
    command exercises the factory and the handler body, so those regressions fail
    here."""
    project = _generate(tmp_path)
    plan = plan_add_slice(str(project), "aggregate", "Order")
    _materialize(project, plan)

    completed = subprocess.run(
        [sys.executable, "-c", _INIT_AND_EXERCISE],
        cwd=project,
        env=_subprocess_env(project),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, (
        "the domain must init and process the planned slice's command:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
    line = next(
        (ln for ln in completed.stdout.splitlines() if ln.startswith("NAMES:")),
        "",
    )
    registered = set(line[len("NAMES:") :].split(","))
    for element in ("Order", "CreateOrder", "OrderCreated", "OrderCommandHandler"):
        assert element in registered, (
            f"{element} did not register under traversal; registered: "
            f"{sorted(registered)}"
        )
    # The command ran through the generated handler and the aggregate came back.
    assert "PERSISTED:Widget" in completed.stdout, (
        "the generated handler did not create and persist the aggregate:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_unsupported_type_exits_nonzero_and_writes_nothing(tmp_path):
    project = _generate(tmp_path)

    before = _snapshot(project)
    result = CliRunner().invoke(app, ["add", "widget", "Foo", "--path", str(project)])
    after = _snapshot(project)

    # 2 is the documented usage exit code; pin it, not just "non-zero".
    assert result.exit_code == 2, result.output
    assert "aggregate" in result.output, (
        f"the error should name aggregate as the supported type:\n{result.output}"
    )
    assert before == after, "a rejected add must not touch the project tree"


def test_keyword_name_exits_two_and_writes_nothing(tmp_path):
    """A Python keyword would produce a slice that does not compile, so the
    command must reject it with the usage exit code and write nothing."""
    project = _generate(tmp_path)

    before = _snapshot(project)
    result = CliRunner().invoke(
        app, ["add", "aggregate", "class", "--path", str(project)]
    )
    after = _snapshot(project)

    assert result.exit_code == 2, result.output
    assert "keyword" in result.output, (
        f"the error should explain the name is a Python keyword:\n{result.output}"
    )
    assert before == after, "a rejected add must not touch the project tree"
