"""Intra-procedural dataflow over a single method body.

:class:`DataflowAnalyzer` is the fourth layer of the ``protean check`` behavioral
substrate. The first three turn a domain into parsed trees
(:class:`~protean.ir.analysis.source_provider.SourceProvider`), a class/method
index (:class:`~protean.ir.analysis.element_index.ElementIndex`) and a name
resolver (:class:`~protean.ir.analysis.symbols.SymbolResolver`); this one looks
*inside* one method body and answers the three questions a rule needs to link
facts across statements:

- **Statement ordering.** Every statement in the body carries a document-order
  index, so a rule can ask "does this use come after that assignment?".
- **Intra-procedural def-use.** For a local-name load, which assignment(s) in the
  same body could have bound it at that point — the reaching definitions.
- **Lexical block coverage.** For a statement, the enclosing ``with`` context
  managers (each resolved to an FQN through the shared resolver) and the
  enclosing ``for`` / ``while`` loops, outermost first.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir``.

The one rule: never guess
-------------------------
Like the resolver, every answer has a single "I don't know": an empty reaching
tuple, an ``fqn`` of ``None`` on a context, an absent order. A load that cannot
be tied to a definition is left with the empty tuple rather than bound to a
plausible-but-wrong one, because a wrong definition feeds a downstream false
positive and a miss does not.

May-reach, not must-reach
-------------------------
The reaching-definition analysis is a *may* analysis: a definition is reported
if it *could* reach the use on some path, so a name assigned in both arms of an
``if`` resolves to the set of both assignments, never a single arm. Straight-line
code collapses to exactly one (last write in source order wins). The analysis
over-approximates on purpose — an extra candidate is safe, a dropped true
assignment is the bug that would later hide a lost write. Loops are walked twice
so a use fed by a prior iteration's assignment is not missed, and a loop's
``break`` states are merged into its exit so a definition on the break path
survives an ``else``. ``try`` handlers and ``finally`` blocks see the union of
the entry state and *every* intermediate state of the body, because an exception
can propagate from any point in it. ``del`` and the binding forms this analysis
cannot value — an ``except ... as`` name, a ``match`` capture, an in-body
``import`` — unbind their name, so a use resolves to the empty tuple rather than
a stale prior definition.

What binds a local name
-----------------------
``ast.Assign``, ``ast.AnnAssign`` with a value, ``ast.AugAssign`` (a use *and* a
def of its target), ``for`` / ``with ... as`` targets, and walrus
(``:=``) targets, recursing into tuple/list/starred unpacking. Attribute and
subscript targets (``self.x = ...``, ``a[i] = ...``) bind no local name — they
are attribute writes, a later layer's concern. Parameters are bindings visible
from the top of the body, represented as parameter-origin definitions distinct
from "unresolved".

This body only
--------------
Intra-procedural means the analysis never descends into a nested ``def`` /
``async def`` / ``lambda`` / comprehension / nested ``class``: those are separate
scopes with their own names. A walrus inside a comprehension therefore does not
leak into the outer body's def-use, and the outer body's names do not resolve
into a nested scope. ``async def`` bodies, ``async with`` and ``async for`` are
first-class here — handlers are commonly ``async``, and matching only the sync
nodes would silently yield empty answers for them. A use written in a nested
scope's *header* but evaluated in this scope — a decorator or default argument on
a nested ``def``, a base class, a comprehension's outermost iterable — is a
conservative miss: it resolves to the empty tuple rather than to a wrong
definition.

Contracts
---------
- **Fail open.** A body that cannot be analyzed — unparseable content reachable
  only through a bug, an interpreter limit — yields an empty
  :class:`MethodFlow`, never an exception. A diagnostics pass must not abort on
  one method.
- **Read-only nodes.** Result objects wrap nodes owned by the provider's cached
  trees. Rules must not mutate them.
- **Deterministic.** Reaching tuples and coverage tuples are in a stable order
  (document order, then position), so two runs over the same source agree.
- **Single-threaded.** One analyzer per build, sharing that build's provider and
  resolver; give each thread its own, as with the other layers.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from protean.ir.analysis.source_provider import SourceProvider
from protean.ir.analysis.symbols import SymbolResolver

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from protean.domain import Domain

#: A method body node, sync or async. Every walk must admit both: Protean
#: handlers are commonly ``async def``, and matching only ``ast.FunctionDef``
#: silently yields empty answers for them.
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

#: A loop statement, carried on a statement's coverage. ``async for`` is a loop
#: exactly as ``for`` is.
LoopNode = ast.For | ast.AsyncFor | ast.While

#: Expression nodes that open a new scope. The def-use walk stops at each: a
#: comprehension target, a lambda parameter and a walrus inside a comprehension
#: all belong to a scope that is not this body.
_SCOPE_NODES = (
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)

#: A per-name map from a name to the definitions that may reach the current
#: point. Frozensets so a merge is a union and a copy is shallow.
_State = dict[str, "frozenset[Definition]"]


class DefKind(StrEnum):
    """How a definition binds its name.

    A rule that inspects a reaching definition often cares about the shape of
    the binding — a plain assignment carries an inspectable right-hand side, a
    parameter carries none — so the kind is reported alongside the node.
    """

    ASSIGN = "ASSIGN"
    ANN_ASSIGN = "ANN_ASSIGN"
    AUG_ASSIGN = "AUG_ASSIGN"
    FOR_TARGET = "FOR_TARGET"
    WITH_TARGET = "WITH_TARGET"
    WALRUS = "WALRUS"
    PARAMETER = "PARAMETER"


@dataclass(frozen=True, slots=True)
class Definition:
    """One binding of a local name within a method body."""

    name: str
    kind: DefKind
    #: The binding statement (or the ``ast.arg`` for a parameter). Shared with
    #: the provider's cached tree; do not mutate.
    node: ast.AST
    #: The specific target the name was bound at, when there is one — a plain
    #: ``ast.Name`` in Store context. ``None`` for a parameter.
    target: ast.expr | None
    #: The right-hand side the name was bound to, when a single expression is
    #: statically knowable: an ``Assign`` / ``AnnAssign`` / ``AugAssign`` value,
    #: a ``with`` context expression, a walrus value. ``None`` for a parameter,
    #: a ``for`` target, and an unpacking target (no single value is
    #: attributable to one name). This is the primitive a receiver-role rule
    #: reads: ``repo = current_domain.repository_for(Order)`` binds ``repo`` with
    #: ``value`` set to the ``repository_for(...)`` call.
    value: ast.expr | None
    #: Document-order index of the binding statement; ``-1`` for a parameter,
    #: which is bound before the body's first statement.
    order: int

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Definition {self.name} {self.kind} order {self.order}>"


@dataclass(frozen=True, slots=True)
class WithContext:
    """One ``with`` context manager enclosing a statement."""

    #: The context expression's FQN, resolved through the shared resolver, or
    #: ``None`` when it cannot be resolved to exactly one name. A call like
    #: ``with UnitOfWork():`` resolves its callee, so both import spellings of
    #: ``UnitOfWork`` are recognizable.
    fqn: str | None
    #: The context expression node (``item.context_expr``). Shared with the
    #: cached tree; do not mutate.
    node: ast.expr

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WithContext {self.fqn}>"


@dataclass(frozen=True, slots=True)
class BlockCoverage:
    """The lexical ``with`` / loop blocks enclosing one statement."""

    #: Enclosing ``with`` items, outermost first. A single ``with a, b:`` yields
    #: two, in written order.
    contexts: tuple[WithContext, ...]
    #: Enclosing ``for`` / ``while`` loops, outermost first. Its length is the
    #: loop-nesting depth of the statement.
    loops: tuple[LoopNode, ...]


@dataclass(frozen=True, slots=True)
class MethodFlow:
    """The dataflow facts of one analyzed method body.

    Every lookup answers with the single "unknown" for its kind: an absent order
    is ``None``, an unrecorded load has the empty reaching tuple, an unindexed
    statement has empty coverage. Nothing here raises.
    """

    module: str
    node: FunctionNode
    #: Parameters of the body, in declaration order, as parameter-origin
    #: definitions. A use of a parameter resolves to one of these, distinct from
    #: an unbound name's empty tuple.
    parameters: tuple[Definition, ...]
    _order: dict[int, int]
    _reaching: dict[int, tuple[Definition, ...]]
    _coverage: dict[int, BlockCoverage]
    _statements: tuple[ast.stmt, ...]

    def statements(self) -> tuple[ast.stmt, ...]:
        """Every statement of the body, in document order.

        Statements at every nesting depth of *this* body, flattened in the order
        they are written. Statements inside a nested ``def`` / ``class`` /
        ``lambda`` are not this body's and are absent.
        """
        return self._statements

    def order_of(self, stmt: ast.stmt) -> int | None:
        """The document-order index of ``stmt``, or ``None`` if not in the body.

        Two statements of the same body compare by this index; a smaller index
        is written earlier. ``None`` for a statement that belongs to a different
        body (or a nested scope of this one).
        """
        return self._order.get(id(stmt))

    def reaching(self, use: ast.expr) -> tuple[Definition, ...]:
        """The definitions that may reach a local-name load ``use``.

        ``use`` is a name read inside the body — an ``ast.Name`` in Load
        context. The answer is every definition that could have bound that name
        on some path to this point, in document order. Empty when the name is
        free (never bound in the body and not a parameter), or when ``use`` is
        not a recorded load of this body.
        """
        return self._reaching.get(id(use), ())

    def coverage(self, stmt: ast.stmt) -> BlockCoverage:
        """The ``with`` / loop blocks enclosing ``stmt``.

        Empty coverage for a statement at the body's top level, or one not in
        the body at all.
        """
        return self._coverage.get(id(stmt), _EMPTY_COVERAGE)

    def covered_by(self, stmt: ast.stmt, fqns: Iterable[str]) -> bool:
        """Whether ``stmt`` is inside a ``with`` whose context resolves into ``fqns``.

        A convenience over :meth:`coverage` so a consumer names the surface it
        cares about (the accepted set of ``UnitOfWork`` FQNs, say) and the
        analyzer stays free of that surface. A context that resolved to ``None``
        matches nothing.
        """
        accepted = frozenset(fqns)
        return any(
            context.fqn is not None and context.fqn in accepted
            for context in self.coverage(stmt).contexts
        )


#: Shared empty coverage, returned for any statement with no enclosing block.
_EMPTY_COVERAGE = BlockCoverage((), ())


class DataflowAnalyzer:
    """Answer def-use, ordering and block-coverage questions for a method body.

    One analyzer per :class:`~protean.ir.builder.IRBuilder`, sharing that
    builder's provider and resolver so a module a rule already read is not parsed
    or tabled again. Each body's analysis is done once, on the first
    :meth:`analyze` for that node, and cached for the analyzer's lifetime.
    """

    def __init__(
        self,
        domain: Domain,
        provider: SourceProvider | None = None,
        symbols: SymbolResolver | None = None,
    ) -> None:
        self._domain = domain
        self._provider = provider if provider is not None else SourceProvider(domain)
        self._symbols = (
            symbols if symbols is not None else SymbolResolver(domain, self._provider)
        )
        # ``(module, id(node)) -> MethodFlow``. A node lives in exactly one
        # module, but the module is part of the key so a re-analysis under a
        # different name (the element index's two "doors") is not confused for
        # a cache hit.
        self._cache: dict[tuple[str, int], MethodFlow] = {}

    def analyze(self, module: str, node: FunctionNode) -> MethodFlow:
        """The dataflow facts of ``node``'s body, built once and cached.

        ``module`` is the name the body's module is tabled under in the shared
        resolver — the name whose symbol table resolves the body's ``with``
        context managers. A body that cannot be analyzed yields an empty
        :class:`MethodFlow`; no input makes this raise.
        """
        key = (module, id(node))
        cached = self._cache.get(key)
        if cached is None:
            cached = self._build(module, node)
            self._cache[key] = cached
        return cached

    def _build(self, module: str, node: FunctionNode) -> MethodFlow:
        try:
            return _FlowBuilder(self._symbols).build(module, node)
        # Fail open: the substrate must not abort a diagnostics pass over one
        # pathological body. A genuine interpreter limit (deep nesting) is as
        # much "cannot analyze" here as anything else.
        except Exception:  # pragma: no cover - defensive fail-open
            return MethodFlow(module, node, (), {}, {}, {}, ())


class _FlowBuilder:
    """The single-body worker behind one :meth:`DataflowAnalyzer.analyze`.

    Instantiated fresh per body so its scratch maps never cross bodies — the
    analyzer itself holds no per-build state, which keeps a re-entrant or
    concurrent misuse from corrupting an in-flight build.
    """

    def __init__(self, symbols: SymbolResolver) -> None:
        self._symbols = symbols
        self._module = ""
        self._order: dict[int, int] = {}
        self._reaching: dict[int, tuple[Definition, ...]] = {}
        self._coverage: dict[int, BlockCoverage] = {}
        self._statements: list[ast.stmt] = []
        #: A stack of break-state accumulators, one frame per enclosing loop. A
        #: ``break`` records the current state onto the top frame so the loop can
        #: merge every break-path exit past its ``else``.
        self._break_states: list[list[_State]] = []
        #: A stack of continue-state accumulators, one frame per enclosing loop.
        #: A ``continue`` records the current state onto the top frame so the
        #: next iteration's entry — and, for a ``while``, its re-evaluated
        #: ``test`` — sees a definition made before the ``continue``.
        self._continue_states: list[list[_State]] = []

    def build(self, module: str, node: FunctionNode) -> MethodFlow:
        self._module = module
        self._walk_structure(node.body, (), ())
        parameters, state = self._seed_parameters(node)
        self._run(node.body, state)
        return MethodFlow(
            module,
            node,
            parameters,
            self._order,
            self._reaching,
            self._coverage,
            tuple(self._statements),
        )

    # ------------------------------------------------------------------
    # Structure: statement order and block coverage
    # ------------------------------------------------------------------

    def _walk_structure(
        self,
        stmts: list[ast.stmt],
        contexts: tuple[WithContext, ...],
        loops: tuple[LoopNode, ...],
    ) -> None:
        """Index statements and record their enclosing ``with`` / loop blocks.

        Descends every compound statement of the body but not a nested ``def`` /
        ``class`` — those hold a different scope's statements, which are not this
        body's.
        """
        for stmt in stmts:
            self._order[id(stmt)] = len(self._statements)
            self._statements.append(stmt)
            self._coverage[id(stmt)] = BlockCoverage(contexts, loops)

            if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                self._walk_structure(stmt.body, contexts, (*loops, stmt))
                # ``else`` runs after the loop completes, so it is not nested in
                # the loop it belongs to.
                self._walk_structure(stmt.orelse, contexts, loops)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                added = tuple(
                    WithContext(
                        self._resolve_context(item.context_expr), item.context_expr
                    )
                    for item in stmt.items
                )
                self._walk_structure(stmt.body, (*contexts, *added), loops)
            elif isinstance(stmt, ast.If):
                self._walk_structure(stmt.body, contexts, loops)
                self._walk_structure(stmt.orelse, contexts, loops)
            elif isinstance(stmt, (ast.Try, ast.TryStar)):
                self._walk_structure(stmt.body, contexts, loops)
                for handler in stmt.handlers:
                    self._walk_structure(handler.body, contexts, loops)
                self._walk_structure(stmt.orelse, contexts, loops)
                self._walk_structure(stmt.finalbody, contexts, loops)
            elif isinstance(stmt, ast.Match):
                for case in stmt.cases:
                    self._walk_structure(case.body, contexts, loops)

    def _resolve_context(self, context_expr: ast.expr) -> str | None:
        """The FQN a ``with`` context expression names, or ``None``.

        A call (``with UnitOfWork():``) resolves its callee, so the manager is
        recognized however it is spelled at the call. Anything the resolver
        cannot pin to one name is ``None``, never a wrong FQN.
        """
        target = (
            context_expr.func if isinstance(context_expr, ast.Call) else context_expr
        )
        return self._symbols.resolve(self._module, target)

    # ------------------------------------------------------------------
    # Def-use: reaching definitions
    # ------------------------------------------------------------------

    def _seed_parameters(
        self, node: FunctionNode
    ) -> tuple[tuple[Definition, ...], _State]:
        """The body's parameters, and the entry state they seed.

        Every parameter — positional-only, positional, keyword-only, ``*args``,
        ``**kwargs`` — is a binding visible from the top of the body, so a use of
        one resolves to it rather than to the empty tuple.
        """
        args = node.args
        arguments = [
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
        ]
        if args.vararg is not None:
            arguments.append(args.vararg)
        if args.kwarg is not None:
            arguments.append(args.kwarg)

        parameters: list[Definition] = []
        state: _State = {}
        for argument in arguments:
            definition = Definition(
                argument.arg, DefKind.PARAMETER, argument, None, None, -1
            )
            parameters.append(definition)
            state[argument.arg] = frozenset({definition})
        return tuple(parameters), state

    def _run(self, stmts: list[ast.stmt], state: _State) -> _State | None:
        """Thread ``state`` through a straight-line block of statements.

        ``None`` means the block never falls through — every path exited early
        via ``break`` or ``continue`` — so nothing after it in the same block is
        reachable, and the remaining statements are not walked.
        """
        for stmt in stmts:
            result = self._step(stmt, state)
            if result is None:
                return None
            state = result
        return state

    def _step(self, stmt: ast.stmt, state: _State) -> _State | None:
        """Advance the reaching state across one statement, recording its uses.

        Returns ``None`` for a statement that never falls through to whatever
        follows it in the same block (``break``, ``continue``, or a compound
        statement every one of whose paths does).
        """
        order = self._order.get(id(stmt), -1)

        if isinstance(stmt, ast.If):
            self._record_uses(stmt.test, state, order)
            taken = self._run(stmt.body, _copy(state))
            skipped = (
                self._run(stmt.orelse, _copy(state)) if stmt.orelse else _copy(state)
            )
            return _merge_optional(taken, skipped)

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._record_uses(stmt.iter, state, order)
            entry = _copy(state)
            self._bind(stmt.target, stmt, None, DefKind.FOR_TARGET, entry)
            self._break_states.append([])
            self._continue_states.append([])
            after = self._run_loop_body(stmt.body, entry, state)
            self._continue_states.pop()
            return self._after_loop(after, self._break_states.pop(), stmt.orelse)

        if isinstance(stmt, ast.While):
            self._break_states.append([])
            self._continue_states.append([])
            after = self._run_loop_body(
                stmt.body,
                _copy(state),
                state,
                on_test=lambda invariant: self._record_uses(
                    stmt.test, invariant, order
                ),
            )
            self._continue_states.pop()
            return self._after_loop(after, self._break_states.pop(), stmt.orelse)

        if isinstance(stmt, ast.Break):
            # A break is a possible loop exit that skips the ``else``; record the
            # state so the enclosing loop can merge it in. It does not fall
            # through to whatever follows it in the same block.
            if self._break_states:
                self._break_states[-1].append(_copy(state))
            return None

        if isinstance(stmt, ast.Continue):
            # A continue jumps back to the loop rather than falling through to
            # whatever follows it in the same block; its state instead feeds
            # the next iteration's entry (and a ``while``'s re-evaluated test).
            if self._continue_states:
                self._continue_states[-1].append(_copy(state))
            return None

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            new = _copy(state)
            for item in stmt.items:
                self._record_uses(item.context_expr, new, order)
                if item.optional_vars is not None:
                    self._bind(
                        item.optional_vars,
                        stmt,
                        item.context_expr,
                        DefKind.WITH_TARGET,
                        new,
                    )
            return self._run(stmt.body, new)

        if isinstance(stmt, (ast.Try, ast.TryStar)):
            return self._step_try(stmt, state, order)

        if isinstance(stmt, ast.Match):
            return self._step_match(stmt, state, order)

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # A nested definition is a separate scope. Its body is not this
            # body's, and its own name is not tracked as a data value.
            return state

        return self._step_simple(stmt, state, order)

    def _run_loop_body(
        self,
        body: list[ast.stmt],
        entry: _State,
        before: _State,
        on_test: Callable[[_State], None] | None = None,
    ) -> _State:
        """Analyze a loop body, twice, and return the state after the loop.

        The first pass gives what the body binds; the second pass runs the body
        against the merge of entry and first-pass state, so a use fed by a prior
        iteration's assignment is recorded rather than missed. A ``continue``
        does not fall through the body's end, so it is folded into each pass
        separately rather than carried in the body's own return value. The loop
        may run zero times, so the state after it is the merge of the pre-loop
        state and the body's. ``on_test``, when given, records a ``while``
        test's uses against the invariant a second and later iteration actually
        sees, so a definition the body makes reaches the re-evaluated test.
        """
        first_run = self._run(body, _copy(entry))
        first = _merge(entry, first_run) if first_run is not None else entry
        first = self._fold_continues(first)
        if on_test is not None:
            on_test(first)
        second_run = self._run(body, _copy(first))
        second = second_run if second_run is not None else first
        second = self._fold_continues(second)
        return _merge(before, second)

    def _fold_continues(self, state: _State) -> _State:
        """Merge every ``continue`` exit recorded so far for the innermost loop.

        A ``continue`` jumps back to the loop rather than falling through the
        body's end, so its state never appears in a body pass's own return
        value and is merged in here instead.
        """
        result = state
        for continue_state in self._continue_states[-1]:
            result = _merge(result, continue_state)
        return result

    def _after_loop(
        self, after: _State, breaks: list[_State], orelse: list[ast.stmt]
    ) -> _State | None:
        """Merge a loop's exits: normal completion runs ``else``, ``break`` skips it.

        ``else`` runs only when the loop finished without a ``break`` (including
        zero iterations), so it threads onto the normal-completion state; each
        ``break`` is a separate exit that bypasses ``else`` entirely, and every
        one is a may-reach exit merged in so a definition on the break path is not
        dropped. ``None`` only if ``else`` itself never falls through (an outer
        loop's ``break``/``continue``) and there were no ``break`` exits either.
        """
        result: _State | None = self._run(orelse, after) if orelse else after
        for break_state in breaks:
            result = _merge_optional(result, break_state)
        return result

    def _step_try(
        self, stmt: ast.Try | ast.TryStar, state: _State, order: int
    ) -> _State | None:
        """Advance across a ``try`` conservatively.

        A handler — or the ``finally`` — can be entered after *any* prefix of the
        body ran, because an exception may propagate from any statement in it, so
        it sees the union of the entry state and every intermediate state, not
        just the body's fully-executed end state. Missing an intermediate here is
        the "dropped true assignment that later hides a lost write" the module's
        contract forbids. ``else`` runs only on the body's success; ``finally``
        runs on every path, so it runs last on the broad handler entry too. A
        ``break``/``continue`` partway through the body (directly, or through a
        nested block) ends the body early — nothing after it in the body runs or
        raises — so ``handler_entry`` stops accumulating there too.
        """
        handler_entry = _copy(state)
        after_body: _State | None = _copy(state)
        for body_stmt in stmt.body:
            if after_body is None:
                break
            after_body = self._step(body_stmt, after_body)
            if after_body is not None:
                handler_entry = _merge(handler_entry, after_body)

        result: _State | None = (
            self._run(stmt.orelse, _copy(after_body))
            if stmt.orelse and after_body is not None
            else after_body
        )
        for handler in stmt.handlers:
            if handler.type is not None:
                self._record_uses(handler.type, handler_entry, order)
            handler_state = _copy(handler_entry)
            if handler.name is not None:
                # ``except ... as e`` rebinds ``e`` to the caught exception for
                # the handler body; kill any shadowed outer ``e`` so a use
                # resolves to the empty tuple, never a stale prior definition.
                handler_state[handler.name] = frozenset()
            result = _merge_optional(result, self._run(handler.body, handler_state))

        if stmt.finalbody:
            # ``finally`` runs regardless of how the body/handlers exited, so its
            # entry is never bottom: ``handler_entry`` is always a real state.
            finally_entry = (
                handler_entry if result is None else _merge(result, handler_entry)
            )
            return self._run(stmt.finalbody, finally_entry)
        return result

    def _step_match(self, stmt: ast.Match, state: _State, order: int) -> _State:
        """Advance across a ``match``, treating each case as a branch.

        The subject is used once; each case runs from the entry state with its
        capture names killed, so a use of a captured name (in the guard or the
        body) resolves to the empty tuple rather than a stale outer definition
        the capture shadows. The match may match no case, so the entry state is
        merged into the result too. A case whose body always exits early via
        ``break``/``continue`` contributes nothing here — its state is already
        captured by the enclosing loop's exit handling.
        """
        self._record_uses(stmt.subject, state, order)
        result = _copy(state)
        for case in stmt.cases:
            case_state = _copy(state)
            for name in _pattern_names(case.pattern):
                case_state[name] = frozenset()
            if case.guard is not None:
                self._record_uses(case.guard, case_state, order)
            case_result = self._run(case.body, case_state)
            if case_result is not None:
                result = _merge(result, case_result)
        return result

    def _step_simple(self, stmt: ast.stmt, state: _State, order: int) -> _State:
        """Advance across a non-compound statement, recording its uses.

        The three assignment forms are handled explicitly because each binds a
        name; every other simple statement (a call, a ``return``, an ``assert``)
        only reads, so its expression children are recorded as uses and the state
        passes through unchanged.
        """
        if isinstance(stmt, ast.Assign):
            self._record_uses(stmt.value, state, order)
            for target in stmt.targets:
                self._record_uses(target, state, order)
            new = _copy(state)
            for target in stmt.targets:
                self._bind(target, stmt, stmt.value, DefKind.ASSIGN, new)
            return new

        if isinstance(stmt, ast.AnnAssign):
            self._record_uses(stmt.annotation, state, order)
            self._record_uses(stmt.target, state, order)
            if stmt.value is None:
                # A bare annotation (``x: int``) binds no value.
                return state
            self._record_uses(stmt.value, state, order)
            new = _copy(state)
            self._bind(stmt.target, stmt, stmt.value, DefKind.ANN_ASSIGN, new)
            return new

        if isinstance(stmt, ast.Delete):
            new = _copy(state)
            for target in stmt.targets:
                # ``del a[i]`` reads ``a`` and ``i``; a plain ``del x`` reads
                # nothing (its target is in Del context, not Load).
                self._record_uses(target, state, order)
                self._kill(target, new)
            return new

        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            # An in-body import binds a module or imported object this analysis
            # cannot value; kill the name so a use resolves to the empty tuple
            # rather than a prior definition the import shadows.
            new = _copy(state)
            for alias in stmt.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                if bound != "*":
                    new[bound] = frozenset()
            return new

        if isinstance(stmt, ast.AugAssign):
            self._record_uses(stmt.value, state, order)
            # ``x += 1`` reads ``x`` before it writes it. The target is in Store
            # context, so record it as a use explicitly.
            if isinstance(stmt.target, ast.Name):
                self._record_name(stmt.target, state)
            else:
                self._record_uses(stmt.target, state, order)
            new = _copy(state)
            self._bind(stmt.target, stmt, stmt.value, DefKind.AUG_ASSIGN, new)
            return new

        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.expr):
                self._record_uses(child, state, order)
        return state

    def _record_uses(self, expr: ast.expr, state: _State, order: int) -> None:
        """Record every local-name load in ``expr`` against the current state.

        Walks the expression but stops at a nested scope, so a comprehension's
        or a lambda's names are not read as this body's. A walrus binding found
        along the way is applied to ``state`` after its siblings are recorded, so
        it is visible to later statements.
        """
        loads: list[ast.Name] = []
        walruses: list[ast.NamedExpr] = []
        stack: list[ast.AST] = [expr]
        while stack:
            current = stack.pop()
            if isinstance(current, _SCOPE_NODES):
                # A separate scope: its bindings and reads are not this body's.
                continue
            if isinstance(current, ast.Name):
                if isinstance(current.ctx, ast.Load):
                    loads.append(current)
                continue
            if isinstance(current, ast.NamedExpr):
                walruses.append(current)
            stack.extend(ast.iter_child_nodes(current))

        for load in loads:
            self._record_name(load, state)
        for walrus in walruses:
            if isinstance(walrus.target, ast.Name):
                definition = Definition(
                    walrus.target.id,
                    DefKind.WALRUS,
                    walrus,
                    walrus.target,
                    walrus.value,
                    order,
                )
                state[walrus.target.id] = frozenset({definition})

    def _record_name(self, name: ast.Name, state: _State) -> None:
        """Record one name read: its reaching definitions in document order."""
        definitions = state.get(name.id)
        self._reaching[id(name)] = (
            _ordered(definitions) if definitions is not None else ()
        )

    def _bind(
        self,
        target: ast.expr,
        node: ast.stmt,
        value: ast.expr | None,
        kind: DefKind,
        state: _State,
    ) -> None:
        """Bind the local names a target introduces, overwriting prior defs.

        A plain ``ast.Name`` binds; a tuple/list/starred target recurses, each
        plain name binding with no single attributable value; an attribute or
        subscript target binds no local name.
        """
        if isinstance(target, ast.Name):
            definition = Definition(
                target.id, kind, node, target, value, self._order.get(id(node), -1)
            )
            state[target.id] = frozenset({definition})
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind(element, node, None, kind, state)
        elif isinstance(target, ast.Starred):
            self._bind(target.value, node, None, kind, state)
        # Attribute / subscript: not a local name — an attribute write, which a
        # later layer owns, not def-use.

    def _kill(self, target: ast.expr, state: _State) -> None:
        """Unbind the local names a ``del`` target removes.

        A plain ``ast.Name`` is set to the empty set so a later use resolves to
        the empty tuple, never the deleted definition; a tuple/list/starred
        target recurses; an attribute or subscript target removes no local name.
        """
        if isinstance(target, ast.Name):
            state[target.id] = frozenset()
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._kill(element, state)
        elif isinstance(target, ast.Starred):
            self._kill(target.value, state)


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _pattern_names(pattern: ast.pattern) -> set[str]:
    """The names a ``match`` case pattern captures.

    Capture (``case x``), star (``case [*rest]``) and mapping-rest
    (``case {**rest}``) patterns bind names; this collects them across the whole
    pattern so a case body can kill them, since the analysis cannot value a
    captured binding.
    """
    names: set[str] = set()
    for node in ast.walk(pattern):
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name is not None:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            names.add(node.rest)
    return names


def _copy(state: _State) -> _State:
    """A shallow copy of a state — its frozenset values are immutable."""
    return dict(state)


def _merge(left: _State, right: _State) -> _State:
    """The may-reach union of two states: per name, the union of both sets.

    A name bound on only one side keeps that side's set, because the other path
    leaves it unbound and an unbound name adds no candidate.
    """
    merged = dict(left)
    for name, definitions in right.items():
        existing = merged.get(name)
        merged[name] = definitions if existing is None else existing | definitions
    return merged


def _merge_optional(left: _State | None, right: _State | None) -> _State | None:
    """The may-reach union of two flows, either of which may have exited early.

    ``None`` means that side never falls through here — every path on it broke,
    continued, or returned — so it contributes nothing and is dropped rather
    than merged. Both ``None`` propagates: neither side reaches this point.
    """
    if left is None:
        return right
    if right is None:
        return left
    return _merge(left, right)


def _ordered(definitions: Iterable[Definition]) -> tuple[Definition, ...]:
    """Definitions in a stable order: document order, then source position."""
    return tuple(sorted(definitions, key=_sort_key))


def _sort_key(definition: Definition) -> tuple[int, int, int, str]:
    anchor: ast.AST = (
        definition.target if definition.target is not None else definition.node
    )
    lineno = getattr(anchor, "lineno", 0)
    col_offset = getattr(anchor, "col_offset", 0)
    return (definition.order, lineno, col_offset, definition.name)
