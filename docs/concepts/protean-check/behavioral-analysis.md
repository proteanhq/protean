# Behavioral analysis

`protean check` reasons about a domain in two ways. Most rules read the
**Intermediate Representation** (IR), the structural model of aggregates,
fields, handlers and flows. A smaller set of rules needs to know what a method
*body* does: which fields it filters on, what it raises, how a name flows from
one statement to the next. Those questions are answered by the **behavioral
analysis substrate**, a stack of read-only layers over the domain's parsed
source.

!!! note "Internal API"
    The substrate is machinery for Protean's own diagnostic rules. Nothing in
    `protean.ir.analysis` is re-exported from `protean` or `protean.ir`, and its
    shape is not a public contract. This page explains how the diagnostic rules
    use the substrate. It does not document an interface to build on.

## The layers

Each layer builds on the one below it, and every layer **fails open**: a class
with no source, or a body it cannot analyze, yields an empty result rather than
raising, so one unreadable module never aborts a diagnostics pass.

| Layer | What it answers |
|-------|-----------------|
| `SourceProvider` | Parse a module to an `ast.Module`, once, cached. |
| `ElementIndex` | Which classes and methods exist, and each method's role. |
| `SymbolResolver` | What fully-qualified name does a name or attribute chain resolve to? |
| `FactCatalog` | What does one method body do; its calls, attribute reads/writes, and constructions? |
| `DataflowAnalyzer` | How do names and blocks flow inside one body, def-use, ordering, `with`/loop coverage? |

## The view

A rule rarely wants a single layer. To flag an unindexed filter it needs the
element's methods (index), each method's facts (catalog) and, sometimes, the
dataflow behind a receiver (analyzer). `BehavioralView` is the top layer: a
read-only façade that a rule asks instead of wiring the layers together itself.

The view groups the substrate into three query families:

- **elements → methods**: `element_class_entry(cls)`, `element_methods(cls)`.
- **per-method facts**: `element_facts(cls)` (name → `MethodFacts`),
  `method_facts(module, node)`.
- **dataflow**: `method_flow(module, node)` → `MethodFlow`.

Each `IRBuilder` builds a single view once, and the view shares that build's
one `SourceProvider` and `ElementIndex`. Because the view shares them, a module
that one rule already read is not parsed again for its facts or its dataflow.
One parse per run.

## A rule reading the view

A diagnostic rule receives the view the way it receives the IR: as `self.view`,
a lazily-built property on the builder. Every rule is a `_diagnose_*(self, ir)`
method that appends findings to `self._diagnostics`. Besides the three query
families, the view has one helper method, `filter_call_sites(cls)`. The helper
lists a repository's `filter` call-sites and the fields each call filters on:

```python
# fragment
def _diagnose_unindexed_filters(self, ir):
    """Flag a repository filter on a field that carries no index."""
    # Walking `ir` for each repository class and its indexed fields is elided
    # here; the point is how the rule reads the view, then emits.
    for cls, indexed_fields in repositories_and_indexes(ir):
        for site in self.view.filter_call_sites(cls):
            for field in site.field_names:
                if field not in indexed_fields:
                    self._diagnostics.append(
                        {
                            "code": "UNINDEXED_FILTER",
                            "category": "performance",
                            "element": f"{cls.__module__}.{cls.__qualname__}",
                            "level": "warning",
                            "message": (
                                f"`{site.method_name}` filters on "
                                f"`{field}`, which carries no index."
                            ),
                        }
                    )
```

The rule gets the filter call-sites from the view and never reads `FactCatalog`
or `ElementIndex` internals to assemble them. The view is deterministic
(methods in name order, call-sites in source order), so the same source always
produces the same findings in the same order.
