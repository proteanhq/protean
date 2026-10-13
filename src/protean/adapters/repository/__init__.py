"""Package for Concrete Implementations of Protean repositories"""

import collections.abc
import logging
from collections import defaultdict
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from protean.core.repository import BaseRepository, repository_factory
from protean.exceptions import ConfigurationError
from protean.fields.spec import _UNSET
from protean.port.provider import BaseProvider, registry
from protean.utils import IdentityStrategy, IdentityType, _fully_qualified_name
from protean.utils.reflection import id_field

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.utils.container import OptionsMixin

logger = logging.getLogger(__name__)


class Providers(collections.abc.MutableMapping[str, BaseProvider]):
    def __init__(self, domain: "Domain") -> None:
        self.domain = domain
        self._providers: dict[str, BaseProvider] | None = None

        # Recognized Repositories are memoized within providers
        # for subsequent calls.
        #
        # Structure:
        # {
        #    'app.User': {
        #        'ALL': UserRepository,
        #        'sqlite': UserSQLiteRepository,
        #        'postgresql': UserPostgresRepository,
        #    }
        # }
        self._repositories: dict[str, dict[str, type[BaseRepository]]] = defaultdict(
            dict
        )

    def __getitem__(self, key: str) -> BaseProvider:
        if not self._providers:
            raise KeyError(key)
        return self._providers[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._providers) if self._providers else iter({})

    def __len__(self) -> int:
        return len(self._providers) if self._providers else 0

    def __setitem__(self, key: str, value: BaseProvider) -> None:
        if self._providers is None:
            self._providers = {}

        self._providers[key] = value

    def __delitem__(self, key: str) -> None:
        assert self._providers is not None
        if key in self._providers:
            del self._providers[key]

    def _construct_repository(
        self, part_of: type["OptionsMixin"]
    ) -> type[BaseRepository]:
        repository_cls = type(part_of.__name__ + "Repository", (BaseRepository,), {})
        repository_cls = repository_factory(
            repository_cls, self.domain, part_of=part_of, _auto_constructed=True
        )
        return repository_cls

    def _register_repository(
        self, part_of: type["OptionsMixin"], repository_cls: type[BaseRepository]
    ) -> None:
        # When explicitly provided, the value of `database` will be the actual database in use
        # and will lock the repository to that type of database.
        # For example, with the following PostgreSQL configuration:
        #   databases = {
        #       "default": {
        #           "provider": "postgresql",
        #           "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        #       },
        #   }
        #
        # And repository as:
        #   @domain.repository(part_of=Post, database="postgresql")
        #   class CustomPostRepository:
        #       def custom_method(self):
        #           ...
        #
        # The value of `database` would be `postgresql`.
        #
        # In the absence of an explicit database value, the repository is associated with "ALL"
        # and is used for all databases.
        database = repository_cls.meta_.database

        aggregate_name = _fully_qualified_name(part_of)

        self._repositories[aggregate_name][database] = repository_cls

    def close(self) -> None:
        """Close all provider connections and release resources."""
        if self._providers:
            for name, provider in self._providers.items():
                try:
                    provider.close()
                except Exception:  # one failing provider must not stop closing the rest
                    logger.exception("Error closing provider '%s'", name)
            logger.debug("All providers closed")

    def _initialize(self) -> None:
        """Read config file and initialize providers"""
        # Close existing providers before re-initializing to prevent
        # connection leaks (e.g., when domain.init() is called again).
        self.close()

        configured_providers = self.domain.config["databases"]
        provider_objects: dict[str, BaseProvider] = {}

        if configured_providers and isinstance(configured_providers, dict):
            if "default" not in configured_providers:
                raise ConfigurationError("You must define a 'default' provider")

            for provider_name, conn_info in configured_providers.items():
                provider_type = conn_info.get("provider")
                provider_cls = registry.get(provider_type)
                provider = provider_cls(provider_name, self.domain, conn_info)

                # Initialize a connection to check if everything is ok
                conn = provider.is_alive()
                if not conn:
                    raise ConfigurationError(
                        f"Could not connect to database at {conn_info['database_uri']}"
                    )

                provider_objects[provider_name] = provider

        self._providers = provider_objects

    def validate_identity_capacity(self) -> None:
        """Refuse an integer identity under the ``uuid`` strategy on a SQL provider.

        The ``uuid`` strategy makes an integer identity from ``uuid4().int``, a
        128-bit number. Under a domain ``identity_type`` of ``integer`` the
        column is an SQL integer column, which cannot hold it, so the first save
        would fail. The field's own ``identity_type`` / ``identity_strategy``
        win over the domain configuration, the same rule ``_generate_identity``
        follows. The column type follows only the domain setting, so a field
        that sets ``identity_type="integer"`` on a ``string`` domain gets a text
        column; it is refused all the same, so the rule does not depend on
        where the setting comes from. Identifiers the database assigns
        (``increment=True``) and identifiers with a user-supplied default are
        not generated, so they are skipped.

        Raises:
            ConfigurationError: An aggregate on a SQLAlchemy provider would get
                a 128-bit integer identity.
        """
        try:
            # SQLAlchemy is an optional extra; without it no SQL provider exists.
            from protean.adapters.repository.sqlalchemy import (  # noqa: PLC0415
                SAProvider,
            )
        except ImportError:  # pragma: no cover - sqlalchemy backs every SAProvider
            return

        providers = self._providers or {}
        config = self.domain.config
        for record in self.domain.registry.aggregates.values():
            aggregate_cls = record.cls
            provider = providers.get(aggregate_cls.meta_.provider)
            if not isinstance(provider, SAProvider):
                continue

            id_fld = id_field(aggregate_cls)
            if id_fld is None or getattr(id_fld, "increment", False):
                continue

            spec = getattr(aggregate_cls, "__protean_field_meta__", {}).get(
                id_fld.field_name
            )
            if spec is not None:
                if (
                    spec.field_kind not in ("identifier", "auto")
                    or spec.default is not _UNSET
                    or getattr(spec, "_increment", False)
                ):
                    continue
                identity_type = getattr(spec, "_identity_type", None)
                identity_strategy = getattr(spec, "_identity_strategy", None)
            elif getattr(id_fld, "_auto_generated", False):
                identity_type = identity_strategy = None
            else:
                continue

            identity_type = identity_type or config["identity_type"]
            identity_strategy = identity_strategy or config["identity_strategy"]
            if (
                identity_type == IdentityType.INTEGER.value
                and identity_strategy == IdentityStrategy.UUID.value
            ):
                raise ConfigurationError(
                    f"Aggregate `{aggregate_cls.__name__}` uses an integer "
                    f"identity under the `uuid` identity strategy, on provider "
                    f"`{provider.name}` ({provider.__database__}). The `uuid` "
                    f"strategy makes a 128-bit integer, and no SQL integer "
                    f'column holds it. Set `identity_strategy = "function"` '
                    f"with an `identity_function` that returns integers that "
                    f"fit the column, so the id is set when the aggregate is "
                    f"created. Or declare the identifier as "
                    f"`Auto(increment=True)`, so the database assigns the id "
                    f"on the first save."
                )

    def get_connection(self, provider_name: str = "default") -> Any:
        """Fetch connection from Provider"""
        if self._providers is None:
            self._initialize()

        assert self._providers is not None

        if provider_name not in self._providers:
            configured = sorted(self._providers.keys()) if self._providers else []
            raise ConfigurationError(
                f"No provider configured with name '{provider_name}'. "
                f"Configured providers: {', '.join(configured) or 'none'}"
            )
        return self._providers[provider_name].get_connection()

    def repository_for(self, part_of: type["OptionsMixin"]) -> BaseRepository:
        """Retrieve a Repository registered for the Aggregate"""
        if self._providers is None:
            self._initialize()

        provider_name = part_of.meta_.provider
        assert self._providers is not None

        if provider_name not in self._providers:
            configured = sorted(self._providers.keys()) if self._providers else []
            raise ConfigurationError(
                f"No provider configured with name '{provider_name}'. "
                f"Configured providers: {', '.join(configured) or 'none'}"
            )
        provider = self._providers[provider_name]
        database = provider.__class__.__database__

        aggregate_name = _fully_qualified_name(part_of)

        # One-time repository registration process for Aggregates
        #
        # We first cycle through repositories registered with the domain
        # and cache them within providers. We also construct a generic
        # repository dynamically that would work with the other providers.
        if aggregate_name not in self._repositories:
            # First, register all explicitly-defined repositories
            for repository in self.domain.registry.repositories.values():
                if repository.cls.meta_.part_of.__name__ == part_of.__name__:
                    self._register_repository(part_of, repository.cls)

            # Next, check if a generic repository has been registered, otherwise construct
            if "ALL" not in self._repositories[aggregate_name]:
                self._register_repository(part_of, self._construct_repository(part_of))

        # If the aggregate is tied to a database, return the database-specific repository
        if database in self._repositories[aggregate_name]:
            repository_cls = self._repositories[aggregate_name][database]
        # Else return the generic repository
        else:
            repository_cls = self._repositories[aggregate_name]["ALL"]

        return repository_cls(self.domain, provider)
