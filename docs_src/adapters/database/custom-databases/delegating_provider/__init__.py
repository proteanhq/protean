# --8<-- [start:full]
# --8<-- [start:provider]
from collections.abc import Mapping
from typing import Any

from protean import Domain
from protean.adapters.repository.memory import MemoryProvider
from protean.fields import String
from protean.infra.registry import providers
from protean.port.provider import (
    BaseProvider,
    DatabaseCapabilities,
    ProviderHealth,
    RawQueryProviderPort,
)


class DelegatingProvider(BaseProvider, RawQueryProviderPort):
    """A provider that hands every operation to an in-memory MemoryProvider.

    Replace the delegate calls with calls to your database client.
    """

    # The database name Protean reads to pick database-specific behavior
    database_type = "delegating_memory"

    def __init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None:
        super().__init__(name, domain, config)
        # Initialize your database client here
        self._delegate = MemoryProvider(name, domain, config)

    @property
    def capabilities(self) -> DatabaseCapabilities:
        """Declare only the capabilities the adapter implements."""
        return self._delegate.capabilities

    # Connections and sessions
    def get_session(self) -> Any:
        return self._delegate.get_session()

    def get_connection(self) -> Any:
        return self._delegate.get_connection()

    def ping(self) -> bool:
        return self._delegate.ping()

    def health(self) -> ProviderHealth:
        return self._delegate.health()

    # Data access objects and database models
    def dao_for(self, entity_cls: type[Any], model_cls: type[Any]) -> Any:
        return self._delegate.dao_for(entity_cls, model_cls)

    def model_for(
        self, entity_cls: type[Any], model_cls: type[Any] | None = None
    ) -> type[Any]:
        return self._delegate.model_for(entity_cls, model_cls)

    # Raw queries and lifecycle
    def raw(self, query: Any, data: Any = None) -> Any:
        return self._delegate.raw(query, data)

    def clear(self) -> None:
        self._delegate.clear()


# Register the lookups the delegate understands, so none of the required ones are missing
for lookup in MemoryProvider.get_lookups().values():
    DelegatingProvider.register_lookup(lookup)

# Make the provider available as `provider = "delegating_memory"`
providers.register("delegating_memory", f"{__name__}.DelegatingProvider")
# --8<-- [end:provider]

# --8<-- [start:usage]
domain = Domain(name="CustomDatabase")
domain.config["databases"]["default"] = {"provider": "delegating_memory"}


@domain.aggregate
class Customer:
    name: String(max_length=50, required=True)


domain.init(traverse=False)

with domain.domain_context():
    repo = domain.repository_for(Customer)
    repo.add(Customer(id="c-1", name="Ada"))

    customer = repo.get("c-1")
# --8<-- [end:usage]
# --8<-- [end:full]
