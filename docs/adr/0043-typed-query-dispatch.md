# ADR-0043: Typed query dispatch through a generic query base

**Status:** Accepted

**Date:** September 2026

## Context

`domain.dispatch(query)` runs a query and returns whatever its handler returns. The return type was `Any`, so the call site lost the result type. A caller who dispatched a query for an `OrderSummary` got back `Any` and had to annotate or cast to recover the type, and nothing checked that the annotation matched what the handler actually returns.

A query already knows its result type in the domain author's head: the handler for `GetOrderSummary` returns an `OrderSummary`. We want that fact written once, on the query, and carried to every `dispatch` call site by both type checkers Protean supports: mypy (which can run the Protean mypy plugin) and pyright (which cannot, because the plugin is a mypy plugin).

Three shapes could record the result type on a query:

1. A generic base: `class GetOrderSummary(BaseQuery[OrderSummary])`.
2. A class attribute: `__result__ = OrderSummary`.
3. A decorator argument: `@read(returns=OrderSummary)` or similar.

Only the generic base is visible to a plain type checker. `__result__` and the decorator argument are runtime values; a checker cannot read them without a plugin, so under pyright both degrade to `Any` and the feature only half works. The generic base is standard typing, so mypy and pyright both resolve it with no plugin.

## Decision

`BaseQuery` becomes `Generic[TResult]`. `TResult` is a phantom type parameter: it never appears in a field and has no runtime effect. It records the type the query's handler returns, and defaults to `Any` (PEP 696) so that a bare `BaseQuery` subclass keeps checking clean under `disallow_any_generics`. The default comes from `typing_extensions.TypeVar`, because `typing.TypeVar` only took parameter defaults in Python 3.13 and Protean supports 3.11 up. A query declares its result type by subscripting the base:

```python
class GetOrderSummary(BaseQuery[OrderSummary]):
    order_id = Identifier(required=True)
```

`Domain.dispatch` gets two overloads:

```python
@overload
def dispatch(self, query: BaseQuery[_QueryResult]) -> _QueryResult: ...
@overload
def dispatch(self, query: BaseQuery[Any]) -> Any: ...
```

A typed query resolves to its declared result type; an untyped query (`BaseQuery[Any]`, which is what a bare `BaseQuery` subclass means) resolves to `Any`. The runtime implementation is unchanged: it still returns `Any` and its body is untouched. Declaring the result type is optional. Both dispatch identically at runtime.

`dispatch` is never typed `NoReturn`. A missing or unregistered handler stays a runtime `IncorrectUsageError`; it does not show up in the static return type.

The generic composes with the custom subclass hooks `BaseQuery` already runs (`__init_subclass__`, `__pydantic_init_subclass__`, and the value-object descriptor conversion). Subscripting the base builds the same `model_fields` and `__container_fields__` as a bare subclass; this is verified by a runtime test.

## Consequences

- A caller who dispatches a typed query gets the result type back, checked by both mypy and pyright, with no annotation or cast.
- The result type is written once, on the query, next to the query's fields. The handler's return and the query's declared type are two sides that a reviewer can check against each other.
- The feature does not depend on the mypy plugin, so pyright users get it too. This is the reason the generic base was chosen over `__result__` and the decorator argument, both of which degrade to `Any` under pyright.
- Runtime behavior is unchanged. Existing queries keep working, and an untyped query dispatches to `Any` as before.
- Nothing breaks for existing queries, including under a checker that runs `disallow_any_generics` (which mypy's `strict` mode turns on). `TResult` carries a PEP 696 default of `Any`, so a bare `class GetFoo(BaseQuery)` reads as `BaseQuery[Any]` and draws no "missing type arguments" error. Without the default, every bare query in user code that type-checks clean today would start failing that check, which is a cost this feature has no reason to charge. Protean's own `src/` still spells `BaseQuery[Any]` at its internal annotation sites, now for readability rather than necessity.

## Alternatives Considered

The `__result__` class attribute and the `@read(returns=...)` / decorator-argument shapes were both rejected. Each records the result type as a runtime value that a type checker cannot read without a plugin. Under pyright they resolve to `Any`, so the typed-dispatch benefit would exist only for mypy-plugin users. The generic base is the only one of the three that works for both checkers with no plugin, so it was chosen.
