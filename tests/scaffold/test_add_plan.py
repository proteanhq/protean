"""Tests for the ``add`` planner: it plans a create-only aggregate slice and
touches no files.

The planner is pure. It resolves a project from an on-disk ``src/<package>/domain.py``
by AST alone (no import), then returns a :class:`ChangePlan` of
:class:`CreateFileOperation`\\ s in the ADR-0030 canonical layout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.scaffold import ChangePlan, CreateFileOperation
from protean.scaffold.add_plan import AddPlanError, plan_add_slice

pytestmark = pytest.mark.no_test_domain


def _write_project(root: Path, package: str, domain_var: str) -> Path:
    """Lay down the minimum of a canonical project: ``src/<package>/domain.py``
    plus an empty ``shared/`` sibling. Returns the project root."""
    package_dir = root / "src" / package
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")
    (package_dir / "domain.py").write_text(
        "from protean.domain import Domain\n\n"
        f'{domain_var} = Domain(name="{package}")\n'
    )
    shared = package_dir / "shared"
    shared.mkdir()
    (shared / "__init__.py").write_text("")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    """Map every file under *root* to its bytes, so a before/after compare can
    prove the planner wrote nothing."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_plans_five_create_operations_at_canonical_paths(tmp_path):
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    plan = plan_add_slice(str(project), "aggregate", "Order")

    assert isinstance(plan, ChangePlan)
    assert len(plan.operations) > 0, "expected create operations, got none"
    # Every op is a create; nothing edits or patches config.
    assert all(isinstance(op, CreateFileOperation) for op in plan.operations)

    paths = [op.path for op in plan.operations]
    assert paths == [
        "src/myproj/order/__init__.py",
        "src/myproj/order/aggregate.py",
        "src/myproj/order/commands.py",
        "src/myproj/order/events.py",
        "src/myproj/order/command_handlers.py",
    ]


def test_planner_writes_nothing(tmp_path):
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    before = _snapshot(project)
    plan_add_slice(str(project), "aggregate", "Order")
    after = _snapshot(project)

    assert before == after, "the planner must not touch the filesystem"


def test_every_planned_file_compiles(tmp_path):
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    plan = plan_add_slice(str(project), "aggregate", "Order")

    assert len(plan.operations) > 0
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        # Raises SyntaxError if the generated content is not valid Python.
        compile(op.content, op.path, "exec")


def test_package_init_is_side_effect_free(tmp_path):
    """ADR-0030 rule 4: the slice's ``__init__.py`` carries a docstring only, no
    imports. A re-export there would risk the traversal cycle from #1316."""
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    plan = plan_add_slice(str(project), "aggregate", "Order")
    init_op = next(
        op
        for op in plan.operations
        if isinstance(op, CreateFileOperation) and op.path.endswith("order/__init__.py")
    )

    for line in init_op.content.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import "), f"unexpected import: {line!r}"
        assert not stripped.startswith("from "), f"unexpected import: {line!r}"


def _content_for(plan: ChangePlan, suffix: str) -> str:
    op = next(
        op
        for op in plan.operations
        if isinstance(op, CreateFileOperation) and op.path.endswith(suffix)
    )
    return op.content


def test_names_follow_the_example_slice(tmp_path):
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    plan = plan_add_slice(str(project), "aggregate", "Order")

    aggregate = _content_for(plan, "aggregate.py")
    assert "class Order:" in aggregate
    assert "from myproj.domain import myproj" in aggregate
    assert "@myproj.aggregate" in aggregate

    assert "class CreateOrder:" in _content_for(plan, "commands.py")
    assert "class OrderCreated:" in _content_for(plan, "events.py")
    assert "class OrderCommandHandler:" in _content_for(plan, "command_handlers.py")


def test_lowercase_name_still_yields_pascal_case_class_and_lowercase_slug(tmp_path):
    """A lower-cased input name produces a PascalCase class and a lower-case dir,
    so ``order`` and ``Order`` both land in ``order/`` with ``class Order``."""
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    plan = plan_add_slice(str(project), "aggregate", "order")

    paths = [op.path for op in plan.operations]
    assert paths[0] == "src/myproj/order/__init__.py"
    assert "class Order:" in _content_for(plan, "aggregate.py")


def test_domain_variable_is_read_from_domain_py_not_assumed(tmp_path):
    """When ``domain.py`` binds a variable that is not the package name, the
    decorators and the import use that variable. Proves the AST resolution and
    rules out a hardcoded package-name assumption."""
    project = _write_project(tmp_path / "proj", "orders", "subdomain")

    plan = plan_add_slice(str(project), "aggregate", "Order")

    aggregate = _content_for(plan, "aggregate.py")
    assert "@subdomain.aggregate" in aggregate
    assert "from orders.domain import subdomain" in aggregate
    # The package directory (import root) is still `orders`, the directory name.
    assert plan.operations[0].path.startswith("src/orders/order/")


def test_resolves_annotated_and_attribute_form_domain_construction(tmp_path):
    """The resolver reads ``app: Domain = protean.Domain(...)`` too: an annotated
    assignment whose value is the attribute form ``<module>.Domain(...)``, not just
    the bare ``app = Domain(...)`` the scaffold emits."""
    package_dir = tmp_path / "proj" / "src" / "myproj"
    package_dir.mkdir(parents=True)
    (package_dir / "domain.py").write_text(
        "import protean\nfrom protean.domain import Domain\n\n"
        'app: Domain = protean.Domain(name="myproj")\n'
    )

    plan = plan_add_slice(str(tmp_path / "proj"), "aggregate", "Order")

    assert "@app.aggregate" in _content_for(plan, "aggregate.py")
    assert "from myproj.domain import app" in _content_for(plan, "aggregate.py")


def test_unsupported_element_type_raises(tmp_path):
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(project), "widget", "Foo")

    assert "aggregate" in str(exc_info.value)


def test_invalid_name_raises(tmp_path):
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(project), "aggregate", "not a name")

    # The message must name the input and explain what a valid name is.
    message = str(exc_info.value)
    assert "not a name" in message
    assert "identifier" in message


@pytest.mark.parametrize(
    "name",
    [
        "class",  # slug `class` -> `class = cls(...)` does not compile
        "for",
        "import",
        "return",
        "lambda",
        "None",  # class `None` -> `class None:` does not compile
        "True",
        "none",  # PascalCase is `None`, still a keyword
    ],
)
def test_keyword_name_raises(tmp_path, name):
    """A Python keyword passes ``str.isidentifier`` but cannot be a class or
    variable name, so the guard must reject it before it emits code that does not
    compile (acceptance #3: the planned content is valid Python)."""
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(project), "aggregate", name)

    assert "keyword" in str(exc_info.value)


def test_every_planned_file_compiles_for_an_awkward_name(tmp_path):
    """Guards the keyword class directly: any name the planner accepts produces
    content that compiles. ``match`` is a soft keyword and a legitimate name, so
    it is planned; its files must still be valid Python."""
    project = _write_project(tmp_path / "proj", "myproj", "myproj")

    plan = plan_add_slice(str(project), "aggregate", "match")

    assert len(plan.operations) > 0
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        compile(op.content, op.path, "exec")


def test_no_src_directory_raises(tmp_path):
    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(tmp_path), "aggregate", "Order")

    assert "src" in str(exc_info.value)


def test_no_domain_py_raises(tmp_path):
    (tmp_path / "src").mkdir()

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(tmp_path), "aggregate", "Order")

    assert "domain.py" in str(exc_info.value)


def test_unparseable_domain_py_raises(tmp_path):
    package_dir = tmp_path / "proj" / "src" / "myproj"
    package_dir.mkdir(parents=True)
    # A real syntax error, so ast.parse raises and the planner surfaces it.
    (package_dir / "domain.py").write_text("def (:\n")

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(tmp_path / "proj"), "aggregate", "Order")

    assert "domain.py" in str(exc_info.value)


def test_domain_py_that_is_not_utf8_raises(tmp_path):
    """A domain.py in some other encoding fails as a usage error, not a traceback."""
    package_dir = tmp_path / "proj" / "src" / "myproj"
    package_dir.mkdir(parents=True)
    (package_dir / "domain.py").write_bytes(
        'myproj = Domain(name="caf\u00e9")\n'.encode("latin-1")
    )

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(tmp_path / "proj"), "aggregate", "Order")

    assert "domain.py" in str(exc_info.value)


def test_more_than_one_package_raises(tmp_path):
    project = _write_project(tmp_path / "proj", "alpha", "alpha")
    # A second composition root under src/ makes the target ambiguous.
    _write_project(project, "beta", "beta")

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(project), "aggregate", "Order")

    message = str(exc_info.value)
    assert "alpha" in message and "beta" in message


def test_domain_py_without_domain_call_raises(tmp_path):
    package_dir = tmp_path / "proj" / "src" / "myproj"
    package_dir.mkdir(parents=True)
    (package_dir / "domain.py").write_text("x = 1\n")

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(tmp_path / "proj"), "aggregate", "Order")

    assert "Domain" in str(exc_info.value)


def test_domain_py_with_non_name_call_target_raises(tmp_path):
    """A call whose function is itself a call (neither a Name nor an Attribute) is
    not a Domain construction; the resolver rejects it rather than crashing."""
    package_dir = tmp_path / "proj" / "src" / "myproj"
    package_dir.mkdir(parents=True)
    (package_dir / "domain.py").write_text("app = make_factory()(name='x')\n")

    with pytest.raises(AddPlanError) as exc_info:
        plan_add_slice(str(tmp_path / "proj"), "aggregate", "Order")

    assert "Domain" in str(exc_info.value)
