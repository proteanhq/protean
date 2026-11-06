# ADAPTER_CALL_IN_DOMAIN

| | |
|---|---|
| **Code** | `ADAPTER_CALL_IN_DOMAIN` |
| **Category** | `bounded_context` |
| **Level** | `warning` |
| **Opt-in** | `[lint].check_adapter_calls = true` |

## What it flags

A domain element whose **method body calls a concrete adapter** under
`protean.adapters`. `protean check` reports one finding per call-site, naming the
element, the method, the adapter symbol, and the source line.

This rule finds runtime coupling inside method bodies. `INFRA_IMPORT_IN_DOMAIN`
reads only module-level imports and does not check method bodies. It reads
method bodies through the [behavioral analysis
substrate](../behavioral-analysis.md). A method can reach an adapter through
`import protean` attribute access
(`protean.adapters.broker.inline.InlineBroker(...)`), and that call is a real
call-site coupling. The module imports only `protean`, so the module-level
import rule's name-prefix check does not see the call.

## Opt-in

The rule is **off by default**. Turn it on in `domain.toml`:

```toml
[lint]
check_adapter_calls = true
```

The rule parses method bodies, a heavier job than the module-import scan in
`INFRA_IMPORT_IN_DOMAIN`. For that reason the rule stays opt-in, as the
decision on the check engine's determinism boundary
([ADR-0019](../../../adr/0019-check-engine-determinism-boundary-and-behavioral-substrate.md))
sets out. The rule has its own flag and does not reuse `check_infra_imports`.
You switch each rule on or off by itself, so turning on the call-site rule
never changes what the import rule does.

## Scope and limits

The rule walks **every non-internal registered domain element** in fqn order:
aggregates, entities, value objects, repositories, handlers, domain services,
process managers and subscribers. It reads the methods **defined in each
element's own class body**. It is deliberately **conservative**: it flags a
call only when the callee **statically resolves** under `protean.adapters`.
When the rule cannot resolve a callee, the call is **skipped, never guessed
at**. The rule stays deterministic in this way, as the decision on the check
engine's determinism boundary (ADR-0019) requires. A callee bound by an import
written inside the method (`from protean.adapters... import X`) resolves for
every use after that import, so the rule flags it like one bound at module
level. The method body can also bind that name in another way (for example an
assignment, a loop target, a nested `def`, a `del` or a `global` declaration),
or import it a second time from a different object. In that case the rule does
not resolve the name and skips every call through it. A parameter of the same
name counts as another binding too, unless the import is a statement of the
method body itself, outside any `if`, `try`, loop or `with`. That import always
runs, so it replaces the argument for every later use.

The rule reads only an element's own top-level methods. It does **not** see an
adapter call in a method inherited from a non-registered base or mixin, in a
class-attribute default, at module level, or nested inside another `def`,
`lambda`, or class within a method. Those are conservative, by-design misses,
not violations the rule certifies absent. In particular, it does not flag:

- **A class that is not a registered domain element**: Only registered elements
  are visited, so a plain helper class calling an adapter is out of scope.
- **A fetched or injected receiver**: An adapter held in a local variable
  (`broker = self.brokers["default"]; broker.publish(...)`) or reached through
  `current_domain.providers[...]` has an unresolvable receiver root.
- **A self-rooted call**: `self._dao.filter(...)` resolves to no FQN, so
  legitimate repository/DAO use is never flagged.

## Why it matters

When a domain method calls into `protean.adapters`, the call couples the domain
layer to a specific adapter at runtime and breaks the ports-and-adapters
boundary. The domain should depend on abstractions, and the domain's provider
configuration should wire in the concrete adapter. You can then swap
infrastructure (memory for tests, Postgres for production) without editing
domain code.

## Example

Flagged, a domain method constructs a concrete broker adapter:

```python
--8<-- "concepts/protean-check/rules/adapter-call-from-domain/001.py:flagged"
```

Compliant, the domain names no adapter. A self-rooted repository call resolves
to no FQN, so the rule does not flag it:

```python
--8<-- "concepts/protean-check/rules/adapter-call-from-domain/002.py:compliant"
```

## How to fix

- Remove the `protean.adapters` call from the domain method.
- Depend on a domain-layer abstraction instead. The domain's provider
  configuration then wires in the adapter.

## Suppressing

Suppress the rule for a single element with `suppress_checks`:

```python
--8<-- "concepts/protean-check/rules/adapter-call-from-domain/003.py:suppressed"
```

To adopt the rule on a codebase with pre-existing violations, exempt the first
*N* findings with the `[lint].suppressions` allow-list:

```toml
[lint]
check_adapter_calls = true
suppressions = { ADAPTER_CALL_IN_DOMAIN = 3 }
```
