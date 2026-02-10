# Testing

Protean is designed with testability at its core. By isolating the domain model
from infrastructure, you can achieve comprehensive test coverage using fast,
in-memory adapters and swap in real technologies only when needed.

!!! note "Coming Soon"
    Detailed testing guides are under construction. The sections below outline
    what will be covered.

## Testing Strategies

Protean supports a layered testing approach:

- **Unit tests** validate domain logic (aggregates, invariants, domain
  services) using in-memory adapters — no infrastructure required.
- **Integration tests** verify adapter behavior with real databases, brokers,
  and event stores using pytest markers (`@pytest.mark.database`,
  `@pytest.mark.broker`, etc.).
- **Event flow tests** exercise end-to-end event processing across aggregates
  and handlers.

## Running Tests

Protean includes a CLI command for running tests with different configurations:

```shell
protean test              # Basic tests with memory adapters
protean test -c DATABASE  # Test all database implementations
protean test -c FULL      # Full test suite with coverage
```

See [CLI > Test](../cli/test.md) for the full list of test configurations.
