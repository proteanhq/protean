"""Static-analysis substrate for ``protean check``.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir`` —
the modules in this package are the shared machinery that IR diagnostic rules
build on, not a public surface.
"""

from __future__ import annotations

from protean.ir.analysis.dataflow import (
    BlockCoverage,
    DataflowAnalyzer,
    Definition,
    DefKind,
    MethodFlow,
    WithContext,
)
from protean.ir.analysis.element_index import (
    ClassEntry,
    ElementIndex,
    MethodEntry,
    MethodRole,
)
from protean.ir.analysis.facts import (
    AttributeFact,
    CallFact,
    ConstructionFact,
    FactCatalog,
    MethodFacts,
    ReceiverRole,
    SourceLocation,
)
from protean.ir.analysis.source_provider import SourceProvider
from protean.ir.analysis.symbols import SymbolResolver

__all__ = [
    "AttributeFact",
    "BlockCoverage",
    "CallFact",
    "ClassEntry",
    "ConstructionFact",
    "DataflowAnalyzer",
    "DefKind",
    "Definition",
    "ElementIndex",
    "FactCatalog",
    "MethodEntry",
    "MethodFacts",
    "MethodFlow",
    "MethodRole",
    "ReceiverRole",
    "SourceLocation",
    "SourceProvider",
    "SymbolResolver",
    "WithContext",
]
