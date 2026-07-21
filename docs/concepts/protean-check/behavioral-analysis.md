# Behavioral analysis

`protean check` reasons about a domain in two ways. Most rules read the
**Intermediate Representation** (IR) — the structural model of aggregates,
fields, handlers and flows. A smaller set of rules needs to know what a method
*body* does: which fields it filters on, what it raises, how a name flows from
one statement to the next. Those questions are answered by the **behavioral
analysis substrate**, a stack of read-only layers over the domain's parsed
source.

!!! note "Internal API"
    The substrate is machinery for Protean's own diagnostic rules. Nothing in
    `protean.ir.analysis` is re-exported from `protean` or `protean.ir`, and its
    shape is not a public contract. This page explains how the rules see it, not
    an interface to build on.

## The layers

Each layer builds on the one below it, and every layer **fails open**: a class
with no source, or a body it cannot analyze, yields an empty result rather than
raising, so one unreadable module never aborts a diagnostics pass.

| Layer | What it answers |
|-------|-----------------|
| `SourceProvider` | Parse a module to an `ast.Module`, once, cached. |
| `ElementIndex` | Which classes and methods exist, and each method's role. |
| `SymbolResolver` | What fully-qualified name does a name or attribute chain resolve to? |
| `FactCatalog` | What does one method body do — its calls, attribute reads/writes, and constructions? |
| `DataflowAnalyzer` | How do names and blocks flow inside one body — def-use, ordering, `with`/loop coverage? |

## The view

A rule rarely wants a single layer. To flag an unindexed filter it needs the
element's methods (index), each method's facts (catalog) and, sometimes, the
dataflow behind a receiver (analyzer). `BehavioralView` is the top layer: a
read-only façade that a rule asks instead of wiring the layers together itself.

The view groups the substrate into three query families:

- **elements → methods** — `element_class_entry(cls)`, `element_methods(cls)`.
- **per-method facts** — `element_facts(cls)` (name → `MethodFacts`),
  `method_facts(module, node)`.
- **dataflow** — `method_flow(module, node)` → `MethodFlow`.

A single view is built once per `IRBuilder` and shares that build's one
`SourceProvider` and `ElementIndex`, so a module a rule already read is not
parsed again for its facts or its dataflow — one parse per run.

## A rule reading the view

A diagnostic rule receives the view the way it receives the IR: as `self.view`,
a lazily-built property on the builder. On top of the three families the view
offers one convenience, `filter_call_sites(cls)`, which enumerates a repository's
`filter` call-sites and the fields each filters on:

```python
def _diagnose_unindexed_filters(self, cls, indexed_fields):
    """Flag a repository filter on a field that carries no index."""
    for site in self.view.filter_call_sites(cls):
        for field in site.field_names:
            if field not in indexed_fields:
                self._emit(
                    "UNINDEXED_FILTER",
                    location=site.location,
                    detail=f"{site.method_name} filters on unindexed {field!r}",
                )
```

The rule never reaches into `FactCatalog` or `ElementIndex` internals to assemble
that answer; it asks the view, and the view's determinism (methods in name order,
call-sites in source order) means the same source always produces the same
findings in the same order.
