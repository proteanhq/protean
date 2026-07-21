"""DataflowAnalyzer: statement order, reaching definitions, block coverage."""

import ast
from pathlib import Path
from textwrap import dedent

import pytest

from protean import Domain
from protean.ir.analysis import (
    BlockCoverage,
    DataflowAnalyzer,
    DefKind,
    SourceProvider,
    SymbolResolver,
)
from protean.ir.builder import IRBuilder
from tests.ir.support import behavioral_domain
from tests.ir.support.behavioral_domain import elements

pytestmark = pytest.mark.no_test_domain

MODULE = "pkg.mod"
PACKAGE_ROOT = str(Path(behavioral_domain.__file__).parent)
ELEMENTS_MODULE = elements.__name__


def _make_pkg(tmp_path, source):
    """Write a ``pkg.mod`` module with ``source`` and return the package root."""
    root = tmp_path / "pkg"
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "mod.py").write_text(dedent(source), encoding="utf-8")
    return root


def _analyzer_for(root):
    """An analyzer whose provider has the package cached under its walked names.

    The on-disk walk caches trees under the names it gives them, so both the
    analyzer's method nodes and the resolver's ``with`` resolution work off the
    same trees, without any import machinery.
    """
    domain = Domain(name="Dataflow", root_path=str(root))
    provider = SourceProvider(domain)
    dict(provider.iter_trees())
    symbols = SymbolResolver(domain, provider)
    return DataflowAnalyzer(domain, provider, symbols), provider


def _find_func(provider, name, module=MODULE):
    """The first function named ``name`` in ``module``, top-level or in a class."""
    tree = provider.tree(module)
    assert tree is not None, f"no source for {module}"
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"no function {name} in {module}")


def _setup(tmp_path, source, func="m"):
    """Write ``source``, return ``(flow, node)`` for the method ``func``."""
    analyzer, provider = _analyzer_for(_make_pkg(tmp_path, source))
    node = _find_func(provider, func)
    return analyzer.analyze(MODULE, node), node


def _load(scope, name):
    """The sole ``ast.Name`` load of ``name`` within ``scope``."""
    loads = [
        n
        for n in ast.walk(scope)
        if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
    ]
    assert len(loads) == 1, f"expected one load of {name}, found {len(loads)}"
    return loads[0]


class TestStatementOrdering:
    def test_statements_carry_a_document_order_index(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m():
                a = 1
                b = 2
            """,
        )

        first, second = node.body[0], node.body[1]

        assert flow.order_of(first) == 0
        assert flow.order_of(second) == 1
        assert flow.order_of(first) < flow.order_of(second)

    def test_nested_statements_are_indexed_in_document_order(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(items):
                for x in items:
                    a = 1
                b = 2
            """,
        )
        loop = node.body[0]
        inner = loop.body[0]
        after = node.body[1]

        assert flow.order_of(loop) == 0
        assert flow.order_of(inner) == 1
        assert flow.order_of(after) == 2
        # Every body statement is reachable through ``statements()``.
        assert set(flow.statements()) == {loop, inner, after}

    def test_a_statement_outside_the_body_has_no_order(self, tmp_path):
        flow, _ = _setup(tmp_path, "def m():\n    a = 1\n")

        assert flow.order_of(ast.parse("z = 1").body[0]) is None


class TestReachingDefinitions:
    def test_a_straight_line_use_resolves_to_its_assignment(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(repo, key):
                x = repo.get(key)
                x.total = 1
            """,
        )
        use = _load(node.body[1], "x")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].node is node.body[0]
        assert reaching[0].kind == DefKind.ASSIGN

    def test_a_reassignment_resolves_to_the_last_write(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(a, b):
                x = a
                x = b
                use(x)
            """,
        )
        use = _load(node.body[2], "x")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].node is node.body[1]

    def test_a_use_between_two_writes_resolves_to_the_first(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(a, b):
                x = a
                use(x)
                x = b
            """,
        )
        use = _load(node.body[1], "x")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].node is node.body[0]

    def test_a_name_assigned_in_both_arms_resolves_to_the_set(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(cond, a, b):
                if cond:
                    x = a
                else:
                    x = b
                use(x)
            """,
        )
        branch = node.body[0]
        use = _load(node.body[1], "x")

        reaching = flow.reaching(use)
        binders = {definition.node for definition in reaching}

        assert len(reaching) == 2
        assert binders == {branch.body[0], branch.orelse[0]}

    def test_a_name_assigned_in_only_one_arm_may_reach(self, tmp_path):
        """An ``if`` without an ``else`` leaves the pre-branch value reaching the
        join too — the branch may not run."""
        flow, node = _setup(
            tmp_path,
            """
            def m(cond, a, b):
                x = a
                if cond:
                    x = b
                use(x)
            """,
        )
        outer = node.body[0]
        inner = node.body[1].body[0]
        use = _load(node.body[2], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {outer, inner}

    def test_a_free_name_resolves_to_the_empty_tuple(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m():
                use(y)
            """,
        )
        use = _load(node.body[0], "y")

        assert flow.reaching(use) == ()

    def test_a_parameter_use_resolves_to_a_parameter_origin(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(self, order):
                use(order)
            """,
        )
        use = _load(node.body[0], "order")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].kind == DefKind.PARAMETER
        assert reaching[0].name == "order"
        assert reaching[0] in flow.parameters

    def test_a_use_fed_by_a_prior_iteration_is_not_missed(self, tmp_path):
        """In a loop, an assignment later in the body reaches an earlier use on
        the next iteration — a may-reach analysis must keep it."""
        flow, node = _setup(
            tmp_path,
            """
            def m(items, seed):
                x = seed
                for item in items:
                    use(x)
                    x = item
            """,
        )
        seed_def = node.body[0]
        loop = node.body[1]
        reassign = loop.body[1]
        use = _load(loop.body[0], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {seed_def, reassign}

    def test_an_annotated_assignment_binds_its_value(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(seed):
                x: int = seed
                use(x)
            """,
        )
        annotated = node.body[0]
        use = _load(node.body[1], "x")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].node is annotated
        assert reaching[0].kind == DefKind.ANN_ASSIGN

    def test_a_bare_annotation_binds_nothing(self, tmp_path):
        """``x: int`` with no value is a declaration, not a binding, so a use
        after it does not resolve to it."""
        flow, node = _setup(
            tmp_path,
            """
            def m():
                x: int
                use(x)
            """,
        )
        use = _load(node.body[1], "x")

        assert flow.reaching(use) == ()

    def test_an_augmented_assignment_reads_then_writes(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(seed):
                total = seed
                total += 1
                use(total)
            """,
        )
        seed_assign = node.body[0]
        aug = node.body[1]
        aug_use = _load(node.body[2], "total")

        # The ``+= 1`` reads the prior ``total`` and then rebinds it.
        assert {d.node for d in flow.reaching(aug.target)} == {seed_assign}
        reaching = flow.reaching(aug_use)
        assert len(reaching) == 1
        assert reaching[0].node is aug
        assert reaching[0].kind == DefKind.AUG_ASSIGN


class TestControlFlowBranches:
    def test_try_and_except_both_may_reach(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(a, b):
                try:
                    x = a
                except Exception:
                    x = b
                use(x)
            """,
        )
        try_stmt = node.body[0]
        body_assign = try_stmt.body[0]
        handler_assign = try_stmt.handlers[0].body[0]
        use = _load(node.body[1], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {body_assign, handler_assign}

    def test_a_finally_assignment_reaches_after_the_try(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(c):
                try:
                    pass
                finally:
                    x = c
                use(x)
            """,
        )
        finally_assign = node.body[0].finalbody[0]
        use = _load(node.body[1], "x")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].node is finally_assign

    def test_match_cases_may_reach(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(subject, a, b):
                match subject:
                    case 1:
                        x = a
                    case _:
                        x = b
                use(x)
            """,
        )
        match_stmt = node.body[0]
        first_case = match_stmt.cases[0].body[0]
        default_case = match_stmt.cases[1].body[0]
        use = _load(node.body[1], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {first_case, default_case}

    def test_a_use_in_a_handler_sees_an_intermediate_body_definition(self, tmp_path):
        """A handler is enterable after any prefix of the body ran, so a name
        reassigned inside the body reaches the handler as the full may-set — the
        intermediate write is not dropped for the body's end state."""
        flow, node = _setup(
            tmp_path,
            """
            def m(a, b):
                try:
                    x = a
                    risky()
                    x = b
                except Exception:
                    use(x)
            """,
        )
        try_stmt = node.body[0]
        first = try_stmt.body[0]
        second = try_stmt.body[2]
        use = _load(try_stmt.handlers[0].body[0], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {first, second}

    def test_a_use_in_a_finally_sees_an_intermediate_body_definition(self, tmp_path):
        """``finally`` runs on every path, including an exception before the body
        finished, so an intermediate write reaches it too."""
        flow, node = _setup(
            tmp_path,
            """
            def m(a, b):
                try:
                    x = a
                    risky()
                    x = b
                finally:
                    use(x)
            """,
        )
        try_stmt = node.body[0]
        first = try_stmt.body[0]
        second = try_stmt.body[2]
        use = _load(try_stmt.finalbody[0], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {first, second}

    def test_an_except_binding_shadows_an_outer_name(self, tmp_path):
        """``except ... as e`` rebinds ``e`` to the caught exception; a use of it
        in the handler resolves to the empty tuple, not the shadowed parameter."""
        flow, node = _setup(
            tmp_path,
            """
            def m(e):
                try:
                    risky()
                except Exception as e:
                    use(e)
            """,
        )
        use = _load(node.body[0].handlers[0].body[0], "e")

        assert flow.reaching(use) == ()

    def test_a_break_path_definition_survives_the_else(self, tmp_path):
        """A loop ``else`` runs only when the loop finished without a ``break``;
        a definition on the break path is a separate exit that must still reach
        past the ``else``."""
        flow, node = _setup(
            tmp_path,
            """
            def m(it, cond, a, b):
                for i in it:
                    x = a
                    if cond:
                        break
                else:
                    x = b
                use(x)
            """,
        )
        loop = node.body[0]
        break_def = loop.body[0]
        else_def = loop.orelse[0]
        use = _load(node.body[1], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {break_def, else_def}

    def test_a_break_does_not_reach_later_statements_in_the_same_iteration(
        self, tmp_path
    ):
        """A ``break`` exits the loop; a definition on that path must not reach a
        statement later in the loop body, even through a nested ``if`` — that
        statement is only ever reached on the non-break path."""
        flow, node = _setup(
            tmp_path,
            """
            def m(it, cond, a, b):
                for i in it:
                    x = b
                    if cond:
                        x = a
                        break
                    use(x)
            """,
        )
        loop = node.body[0]
        b_def = loop.body[0]
        use = _load(loop.body[2], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {b_def}

    def test_a_continue_does_not_reach_later_statements_in_the_same_iteration(
        self, tmp_path
    ):
        """A ``continue`` jumps back to the loop; a definition on that path must
        not reach a statement later in the loop body, even through a nested
        ``if`` — that statement is only ever reached on the other path."""
        flow, node = _setup(
            tmp_path,
            """
            def m(it, cond, a, b):
                for i in it:
                    x = b
                    if cond:
                        x = a
                        continue
                    use(x)
            """,
        )
        loop = node.body[0]
        b_def = loop.body[0]
        use = _load(loop.body[2], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {b_def}

    def test_a_deleted_name_no_longer_reaches(self, tmp_path):
        """``del x`` unbinds ``x``; a use after it resolves to the empty tuple,
        not the killed definition (the name is unbound at runtime)."""
        flow, node = _setup(
            tmp_path,
            """
            def m():
                x = compute()
                del x
                use(x)
            """,
        )
        use = _load(node.body[2], "x")

        assert flow.reaching(use) == ()

    def test_a_match_capture_shadows_an_outer_name(self, tmp_path):
        """A capture pattern rebinds its name for the case; a use of it resolves
        to the empty tuple, not the shadowed parameter."""
        flow, node = _setup(
            tmp_path,
            """
            def m(x, subject):
                match subject:
                    case [x]:
                        use(x)
            """,
        )
        use = _load(node.body[0].cases[0].body[0], "x")

        assert flow.reaching(use) == ()

    def test_an_in_body_import_shadows_an_outer_name(self, tmp_path):
        """An in-body import binds a name this analysis cannot value; a use of it
        resolves to the empty tuple, not the shadowed parameter."""
        flow, node = _setup(
            tmp_path,
            """
            def m(data):
                import data
                use(data)
            """,
        )
        use = _load(node.body[1], "data")

        assert flow.reaching(use) == ()


class TestBindingForms:
    def test_a_walrus_binds_a_reachable_definition(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(items):
                if (n := len(items)):
                    use(n)
            """,
        )
        use = _load(node.body[0].body[0], "n")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].kind == DefKind.WALRUS

    def test_tuple_unpacking_binds_each_name(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(pair):
                a, b = pair
                use(a)
                use(b)
            """,
        )
        assign = node.body[0]
        use_a = _load(node.body[1], "a")
        use_b = _load(node.body[2], "b")

        assert [d.node for d in flow.reaching(use_a)] == [assign]
        assert [d.node for d in flow.reaching(use_b)] == [assign]

    def test_starred_unpacking_binds_the_rest_name(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(items):
                first, *rest = items
                use(rest)
            """,
        )
        assign = node.body[0]
        use = _load(node.body[1], "rest")

        assert [d.node for d in flow.reaching(use)] == [assign]

    def test_a_for_target_is_a_reachable_definition(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(items):
                for item in items:
                    use(item)
            """,
        )
        use = _load(node.body[0].body[0], "item")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].kind == DefKind.FOR_TARGET

    def test_a_with_target_is_a_reachable_definition(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(path):
                with open(path) as handle:
                    use(handle)
            """,
        )
        use = _load(node.body[0].body[0], "handle")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        assert reaching[0].kind == DefKind.WITH_TARGET

    def test_a_use_fed_by_a_prior_while_iteration_is_not_missed(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(seed, cond):
                x = seed
                while cond:
                    use(x)
                    x = step(x)
            """,
        )
        seed_def = node.body[0]
        loop = node.body[1]
        reassign = loop.body[1]
        use = _load(loop.body[0], "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {seed_def, reassign}

    def test_a_while_test_sees_a_definition_from_the_loop_body(self, tmp_path):
        """The ``while`` test is re-evaluated every iteration, not just before
        the first one, so a definition the body makes must reach it too."""
        flow, node = _setup(
            tmp_path,
            """
            def m(seed):
                x = seed
                while has_next(x):
                    x = advance(x)
            """,
        )
        seed_def = node.body[0]
        loop = node.body[1]
        reassign = loop.body[0]
        use = _load(loop.test, "x")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {seed_def, reassign}

    def test_vararg_and_kwarg_parameters_are_reachable(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(*args, **kwargs):
                use(args)
                use(kwargs)
            """,
        )
        args_use = _load(node.body[0], "args")
        kwargs_use = _load(node.body[1], "kwargs")

        assert [d.kind for d in flow.reaching(args_use)] == [DefKind.PARAMETER]
        assert [d.kind for d in flow.reaching(kwargs_use)] == [DefKind.PARAMETER]
        assert {p.name for p in flow.parameters} == {"args", "kwargs"}

    def test_a_match_guard_records_its_uses(self, tmp_path):
        """A guard runs before the case body; a parameter it reads resolves to
        the parameter origin, and a captured name it reads resolves to empty."""
        flow, node = _setup(
            tmp_path,
            """
            def m(subject, threshold):
                match subject:
                    case [value] if value > threshold:
                        pass
            """,
        )
        guard = node.body[0].cases[0].guard
        threshold_use = _load(guard, "threshold")
        value_use = _load(guard, "value")

        assert [d.kind for d in flow.reaching(threshold_use)] == [DefKind.PARAMETER]
        assert flow.reaching(value_use) == ()


class TestReceiverResolution:
    def test_a_variable_receiver_resolves_to_its_assignment_rhs(self, tmp_path):
        """The #1222 feed: a repository bound to a local resolves to the
        ``repository_for(...)`` call that produced it, ready for a later rule to
        classify the receiver's role."""
        flow, node = _setup(
            tmp_path,
            """
            def m(order_id):
                repo = current_domain.repository_for(Order)
                repo.get(order_id)
            """,
        )
        assignment = node.body[0]
        use = _load(node.body[1], "repo")

        reaching = flow.reaching(use)

        assert len(reaching) == 1
        definition = reaching[0]
        assert definition.node is assignment
        assert isinstance(definition.value, ast.Call)
        assert isinstance(definition.value.func, ast.Attribute)
        assert definition.value.func.attr == "repository_for"


class TestWithCoverage:
    def test_a_statement_inside_a_with_reports_the_context_fqn(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            from protean import UnitOfWork

            def m():
                with UnitOfWork():
                    persist()
            """,
        )
        inside = node.body[0].body[0]

        coverage = flow.coverage(inside)

        assert [context.fqn for context in coverage.contexts] == ["protean.UnitOfWork"]
        assert flow.covered_by(inside, {"protean.UnitOfWork"})

    def test_the_submodule_import_spelling_resolves_too(self, tmp_path):
        """Resolution, not string-matching: the fully-qualified import spelling
        resolves to its own FQN, which the consumer's accepted set includes."""
        flow, node = _setup(
            tmp_path,
            """
            from protean.core.unit_of_work import UnitOfWork

            def m():
                with UnitOfWork():
                    persist()
            """,
        )
        inside = node.body[0].body[0]
        accepted = {"protean.UnitOfWork", "protean.core.unit_of_work.UnitOfWork"}

        coverage = flow.coverage(inside)

        assert [c.fqn for c in coverage.contexts] == [
            "protean.core.unit_of_work.UnitOfWork"
        ]
        assert flow.covered_by(inside, accepted)

    def test_the_same_statement_outside_the_with_is_not_covered(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            from protean import UnitOfWork

            def m():
                with UnitOfWork():
                    persist()
                persist()
            """,
        )
        outside = node.body[1]

        assert flow.coverage(outside).contexts == ()
        assert not flow.covered_by(outside, {"protean.UnitOfWork"})

    def test_an_unresolvable_context_is_carried_as_none(self, tmp_path):
        """A context manager that resolves to nothing is carried as ``None``,
        never dropped and never a wrong FQN."""
        flow, node = _setup(
            tmp_path,
            """
            def m():
                with unknown_manager():
                    persist()
            """,
        )
        inside = node.body[0].body[0]

        coverage = flow.coverage(inside)

        assert len(coverage.contexts) == 1
        assert coverage.contexts[0].fqn is None
        assert not flow.covered_by(inside, {"protean.UnitOfWork"})

    def test_a_subscript_context_is_carried_as_none(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(managers):
                with managers[0]:
                    persist()
            """,
        )
        inside = node.body[0].body[0]

        assert flow.coverage(inside).contexts[0].fqn is None

    def test_a_top_level_statement_has_empty_coverage(self, tmp_path):
        flow, node = _setup(tmp_path, "def m():\n    persist()\n")

        assert flow.coverage(node.body[0]) == BlockCoverage((), ())


class TestLoopNesting:
    def test_a_statement_in_a_loop_reports_the_loop(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(orders):
                for order in orders:
                    persist(order)
            """,
        )
        loop = node.body[0]
        inside = loop.body[0]

        assert flow.coverage(inside).loops == (loop,)

    def test_a_doubly_nested_loop_reports_both_outermost_first(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(rows):
                for row in rows:
                    for cell in row:
                        persist(cell)
            """,
        )
        outer = node.body[0]
        inner = outer.body[0]
        inside = inner.body[0]

        assert flow.coverage(inside).loops == (outer, inner)

    def test_a_statement_outside_any_loop_reports_none(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(orders):
                for order in orders:
                    persist(order)
                done()
            """,
        )
        after = node.body[1]

        assert flow.coverage(after).loops == ()


class TestAsyncParity:
    def test_an_async_body_is_analyzed_like_a_sync_one(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            from protean import UnitOfWork

            async def m(items):
                async with UnitOfWork():
                    async for item in items:
                        repo = current_domain.repository_for(Order)
                        repo.add(item)
            """,
        )
        with_stmt = node.body[0]
        loop = with_stmt.body[0]
        assignment = loop.body[0]
        add_stmt = loop.body[1]
        use = _load(add_stmt, "repo")

        coverage = flow.coverage(add_stmt)

        assert [c.fqn for c in coverage.contexts] == ["protean.UnitOfWork"]
        assert coverage.loops == (loop,)
        reaching = flow.reaching(use)
        assert len(reaching) == 1
        assert reaching[0].node is assignment


class TestScopeBoundaries:
    def test_a_comprehension_target_does_not_leak(self, tmp_path):
        """An outer binding of the comprehension's target still reaches: the
        comprehension's own ``y`` is a separate scope and does not overwrite it."""
        flow, node = _setup(
            tmp_path,
            """
            def m(items):
                y = 0
                total = [y for y in items]
                use(y)
            """,
        )
        outer = node.body[0]
        use = _load(node.body[2], "y")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {outer}

    def test_a_nested_functions_binding_does_not_leak(self, tmp_path):
        """The nested ``def``'s ``z = 1`` does not overwrite the outer ``z``;
        the outer binding is what reaches the use."""
        flow, node = _setup(
            tmp_path,
            """
            def m():
                z = 0
                def inner():
                    z = 1
                use(z)
            """,
        )
        outer = node.body[0]
        use = _load(node.body[2], "z")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {outer}

    def test_a_lambda_parameter_does_not_leak(self, tmp_path):
        """The lambda's parameter ``w`` is a separate scope; the outer ``w``
        binding still reaches the use after it."""
        flow, node = _setup(
            tmp_path,
            """
            def m():
                w = 0
                f = lambda w: w + 1
                use(w)
            """,
        )
        outer = node.body[0]
        use = _load(node.body[2], "w")

        binders = {definition.node for definition in flow.reaching(use)}

        assert binders == {outer}


class TestFailOpen:
    def test_an_ellipsis_body_yields_empty_answers(self, tmp_path):
        flow, node = _setup(tmp_path, "def m():\n    ...\n")

        assert len(flow.statements()) == 1
        assert flow.order_of(node.body[0]) == 0
        assert flow.coverage(node.body[0]) == BlockCoverage((), ())

    def test_a_free_name_query_never_raises(self, tmp_path):
        flow, _ = _setup(tmp_path, "def m():\n    pass\n")

        # A load node from another tree is simply unrecorded, not an error.
        stray = ast.parse("q", mode="eval").body
        assert flow.reaching(stray) == ()


class TestDeterminism:
    SOURCE = """
    from protean import UnitOfWork

    def m(cond, a, b, items):
        x = a
        if cond:
            x = b
        with UnitOfWork():
            for item in items:
                use(x)
    """

    def test_two_analyzers_over_the_same_source_agree(self, tmp_path):
        root = _make_pkg(tmp_path, self.SOURCE)
        first_analyzer, first_provider = _analyzer_for(root)
        second_analyzer, second_provider = _analyzer_for(root)

        first = first_analyzer.analyze(MODULE, _find_func(first_provider, "m"))
        second = second_analyzer.analyze(MODULE, _find_func(second_provider, "m"))

        first_use = _load(first.node, "x")
        second_use = _load(second.node, "x")

        def _shape(flow, use):
            return [(d.name, d.kind, d.order) for d in flow.reaching(use)]

        assert _shape(first, first_use) == _shape(second, second_use)
        assert _shape(first, first_use)  # non-empty: the branch reaches two defs

    def test_reaching_order_is_stable(self, tmp_path):
        flow, node = _setup(
            tmp_path,
            """
            def m(cond, a, b):
                if cond:
                    x = a
                else:
                    x = b
                use(x)
            """,
        )
        branch = node.body[0]
        use = _load(node.body[1], "x")

        reaching = flow.reaching(use)

        # ``x = a`` is statement 1, ``x = b`` statement 2 (the ``if`` is 0); the
        # tuple is in that concrete document order, then source position.
        assert [definition.order for definition in reaching] == [1, 2]
        assert [definition.node for definition in reaching] == [
            branch.body[0],
            branch.orelse[0],
        ]


class TestCaching:
    def test_analysis_is_cached_per_node(self, tmp_path):
        analyzer, provider = _analyzer_for(_make_pkg(tmp_path, "def m():\n    a = 1\n"))
        node = _find_func(provider, "m")

        assert analyzer.analyze(MODULE, node) is analyzer.analyze(MODULE, node)


class TestBuilderWiring:
    def test_analyzer_shares_the_builders_provider(self):
        domain = Domain(name="Wiring", root_path=PACKAGE_ROOT)
        domain.register(elements.Wallet, event_sourced=True)
        domain.init(traverse=False)
        builder = IRBuilder(domain)
        analyzer = DataflowAnalyzer(domain, builder.source)

        tree = builder.source.tree(ELEMENTS_MODULE)
        assert tree is not None
        rename = _find_func(builder.source, "rename", ELEMENTS_MODULE)
        flow = analyzer.analyze(ELEMENTS_MODULE, rename)

        # ``rename(self, label)`` assigns ``self.balance = label`` — an attribute
        # target binds no local, and ``label`` is a parameter.
        assert {p.name for p in flow.parameters} == {"self", "label"}
        # The docstring and the assignment: both are statements of the body.
        assert len(flow.statements()) == 2
        label_use = _load(rename.body[-1], "label")
        assert [d.kind for d in flow.reaching(label_use)] == [DefKind.PARAMETER]
