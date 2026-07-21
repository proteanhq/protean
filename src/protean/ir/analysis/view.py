"""A queryable behavioral view for ``protean check`` diagnostic rules.

:class:`BehavioralView` is the sixth and top layer of the ``protean check``
behavioral substrate. The five below it turn a domain into parsed trees
(:class:`~protean.ir.analysis.source_provider.SourceProvider`), a class/method
index (:class:`~protean.ir.analysis.element_index.ElementIndex`), a name
resolver (:class:`~protean.ir.analysis.symbols.SymbolResolver`), per-method
behavioral facts (:class:`~protean.ir.analysis.facts.FactCatalog`) and
intra-procedural dataflow
(:class:`~protean.ir.analysis.dataflow.DataflowAnalyzer`). This one adds no
analysis of its own: it is a read-only façade that gives a ``_diagnose_*`` rule
one object to ask, so a rule reaches an answer through the view rather than by
wiring the five layers together itself.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir``.

Three query families, plus one convenience
------------------------------------------
The view groups the substrate the way a behavioral rule reads it:

- **elements → methods** — :meth:`element_class_entry` and :meth:`element_methods`
  answer "what are this element's methods?", straight from the index.
- **per-method facts** — :meth:`element_facts` (name → :class:`MethodFacts`) and
  :meth:`method_facts` answer "what does this method body do?", from the catalog.
- **dataflow** — :meth:`method_flow` answers "how do names and blocks flow inside
  this body?", from the analyzer.

On top of those, :meth:`filter_call_sites` is the one ergonomic convenience the
epic's acceptance test names directly: an element's repository ``filter``
call-sites and the fields each filters on, built from the first two families so a
rule never reaches into :class:`FactCatalog`/:class:`ElementIndex` internals to
assemble it.

One parse per run
-----------------
The view owns one resolver, one catalog and one analyzer, all built over the
**same** provider and index it is given — the builder's, when the builder
constructs it — so a module a rule already read through the index is not parsed a
second time for its facts or its dataflow. Passing a provider and index in is how
that sharing is guaranteed; omit them and the view builds fresh ones, which is
only right for a standalone view with no builder to share with.

Contracts
---------
- **Fail open.** Every query delegates to a layer that fails open — an element
  with no source yields empty methods, empty facts and an empty
  :class:`MethodFlow`, never a raise — so the view fails open too, adding no IO
  or lookup of its own that could throw.
- **Deterministic.** The view introduces no ordering: each family's order is the
  layer's (methods and facts by name, facts within a method by ``(line, col)``),
  and :meth:`filter_call_sites` preserves it, enumerating methods in name order
  and call-sites within a method in source order.
- **Read-only.** The nodes and facts handed back belong to the provider's cached
  trees and the layers' caches; a rule must treat them as immutable, as it must
  with the layers directly.
- **Single-threaded.** One view per :class:`~protean.ir.builder.IRBuilder`,
  sharing that build's provider and index; give each thread its own, as with
  every layer below it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from protean.ir.analysis.dataflow import DataflowAnalyzer
from protean.ir.analysis.element_index import ElementIndex
from protean.ir.analysis.facts import FactCatalog, ReceiverRole, SourceLocation
from protean.ir.analysis.source_provider import SourceProvider
from protean.ir.analysis.symbols import SymbolResolver

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.ir.analysis.dataflow import MethodFlow
    from protean.ir.analysis.element_index import ClassEntry, FunctionNode, MethodEntry
    from protean.ir.analysis.facts import MethodFacts

#: The repository-query method whose call-sites
#: :meth:`~BehavioralView.filter_call_sites` reports. ``filter`` is the
#: ``QuerySet`` surface a rule reads to see which fields an element filters
#: on; the other query methods (``find``/``get``/...) are recognized by the
#: catalog but are not "filters".
_FILTER_METHOD = "filter"


@dataclass(frozen=True, slots=True)
class FilterCallSite:
    """One repository ``filter`` call inside an element's method.

    Assembled by :meth:`BehavioralView.filter_call_sites` from the element's
    per-method facts, so a rule gets the enclosing method, the fields the call
    filters on, and where it is, without touching the catalog.
    """

    #: The name of the element method the ``filter`` call is written in.
    method_name: str
    #: The keyword field names the ``filter`` passes, in source order, plus any
    #: names from an inline ``Q(field=...)``. A ``**kwargs`` star contributes
    #: none, so this is empty for a purely dynamic ``filter(**kwargs)``. Carried
    #: through unchanged from the underlying :class:`~protean.ir.analysis.facts.CallFact`.
    field_names: tuple[str, ...]
    location: SourceLocation

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FilterCallSite {self.method_name} line {self.location.line}>"


class BehavioralView:
    """A read-only façade over the behavioral substrate, for diagnostic rules.

    One view per :class:`~protean.ir.builder.IRBuilder`, sharing that builder's
    provider and index so the modules a rule already read are not parsed again
    for its facts or dataflow. Each underlying layer computes on first request
    and caches, so a build whose rules never ask the view pays nothing.
    """

    def __init__(
        self,
        domain: Domain,
        provider: SourceProvider | None = None,
        index: ElementIndex | None = None,
    ) -> None:
        self._domain = domain
        self._provider = provider if provider is not None else SourceProvider(domain)
        self._index = (
            index if index is not None else ElementIndex(domain, self._provider)
        )
        # One resolver, shared by the catalog and the analyzer, so a module's
        # symbol table is built once for both.
        self._resolver = SymbolResolver(domain, self._provider)
        self._facts = FactCatalog(domain, self._provider, self._index, self._resolver)
        self._dataflow = DataflowAnalyzer(domain, self._provider, self._resolver)

    # ------------------------------------------------------------------
    # Elements → methods
    # ------------------------------------------------------------------

    def element_class_entry(self, cls: type) -> ClassEntry | None:
        """The indexed class for ``cls``, or ``None`` (fail open).

        ``None`` when the class has no source, no resolvable module, or a
        qualname the index cannot pin — the same conditions the index reports it
        under.
        """
        return self._index.element_class_entry(cls)

    def element_methods(self, cls: type) -> tuple[MethodEntry, ...]:
        """The methods of ``cls`` as written, sorted by name.

        Empty for a class the index cannot resolve; a rule may loop over the
        result without a guard.
        """
        return self._index.element_methods(cls)

    # ------------------------------------------------------------------
    # Per-method facts
    # ------------------------------------------------------------------

    def element_facts(self, cls: type) -> dict[str, MethodFacts]:
        """Every method of ``cls``, name → its :class:`MethodFacts`.

        In method-name order, empty for an element the index cannot resolve.
        Delegates to the shared catalog, so facts a rule already asked for are
        served from its cache.
        """
        return self._facts.element_facts(cls)

    def method_facts(self, module: str, method: FunctionNode) -> MethodFacts:
        """The facts of one method body, by its module name and node.

        For a rule holding a method node (from :meth:`element_methods` or the
        index) that wants that one body's facts without the whole element map.
        """
        return self._facts.method_facts(module, method)

    # ------------------------------------------------------------------
    # Dataflow
    # ------------------------------------------------------------------

    def method_flow(self, module: str, method: FunctionNode) -> MethodFlow:
        """The intra-procedural dataflow of one method body.

        The :class:`MethodFlow` answers def-use, statement ordering and
        ``with``/loop coverage for names inside ``method``'s body. An
        unanalyzable body yields an empty flow, never a raise.
        """
        return self._dataflow.analyze(module, method)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def filter_call_sites(self, cls: type) -> tuple[FilterCallSite, ...]:
        """Every repository ``filter`` call written in ``cls``'s methods.

        For each method of ``cls`` (in name order), the ``filter`` calls whose
        receiver the catalog recognized as a repository query
        (:attr:`ReceiverRole.REPOSITORY_QUERY`), each carrying the fields it
        filters on. Empty for an element with no such call-site or no source.
        This is the ergonomic parity the issue asks for: a rule that checks
        filtered fields gets them from the view, never by walking
        :class:`MethodFacts` itself.
        """
        return tuple(
            FilterCallSite(method_name, call.field_names, call.location)
            for method_name, facts in self.element_facts(cls).items()
            for call in facts.calls
            if call.method == _FILTER_METHOD
            and call.receiver_role is ReceiverRole.REPOSITORY_QUERY
        )
