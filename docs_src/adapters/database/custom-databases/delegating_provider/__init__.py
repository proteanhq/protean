# --8<-- [start:full]
# --8<-- [start:provider]
from typing import Any

from protean import Domain
from protean.adapters.repository.memory import MemoryProvider
from protean.fields import String
from protean.port.provider import BaseProvider, DatabaseCapabilities, registry


class DelegatingProvider(BaseProvider):
    """A provider that hands every operation to an in-memory MemoryProvider.

    Replace the delegate calls with calls to your database client.
    """

    # The database name Protean reads to pick database-specific behavior
    __database__ = "delegating_memory"

    def __init__(self, name: str, domain: Domain, conn_info: dict[str, Any]) -> None:
        super().__init__(name, domain, conn_info)
        # Initialize your database client here
        self._delegate = MemoryProvider(name, domain, conn_info)

    @property
    def capabilities(self) -> DatabaseCapabilities:
        """Declare only the capabilities the adapter implements."""
        return self._delegate.capabilities

    # Connections and sessions
    def get_session(self) -> Any:
        return self._delegate.get_session()

    def get_connection(self) -> Any:
        return self._delegate.get_connection()

    def is_alive(self) -> bool:
        return self._delegate.is_alive()

    def close(self) -> None:
        self._delegate.close()

    # Data access objects and database models
    def get_dao(self, entity_cls: type[Any], database_model_cls: type[Any]) -> Any:
        return self._delegate.get_dao(entity_cls, database_model_cls)

    def construct_database_model_class(self, entity_cls: type[Any]) -> type[Any]:
        return self._delegate.construct_database_model_class(entity_cls)

    def decorate_database_model_class(
        self, entity_cls: type[Any], database_model_cls: type[Any]
    ) -> type[Any]:
        return self._delegate.decorate_database_model_class(
            entity_cls, database_model_cls
        )

    # Raw queries and lifecycle
    def _raw(self, query: Any, data: Any = None) -> Any:
        return self._delegate._raw(query, data)

    def _data_reset(self) -> None:
        self._delegate._data_reset()

    def _create_database_artifacts(self) -> None:
        self._delegate._create_database_artifacts()

    def _drop_database_artifacts(self) -> None:
        self._delegate._drop_database_artifacts()


# Register the lookups the delegate understands, so none of the required ones are missing
for lookup in MemoryProvider.get_lookups().values():
    DelegatingProvider.register_lookup(lookup)

# Make the provider available as `provider = "delegating_memory"`
registry.register("delegating_memory", f"{__name__}.DelegatingProvider")
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
    assert customer.name == "Ada"
# --8<-- [end:usage]
# --8<-- [end:full]
