"""Package for Concrete Implementations of Protean repositories"""

import collections.abc
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from importlib import metadata
from typing import TYPE_CHECKING, Any

from protean.core.repository import BaseRepository, repository_factory
from protean.exceptions import ConfigurationError
from protean.infra.registry import databases as database_registry
from protean.port.database import BaseDatabase
from protean.utils import DomainObjects, _fully_qualified_name

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.utils.container import OptionsMixin

logger = logging.getLogger(__name__)


def _without_password(uri: Any) -> str:
    """Return ``uri`` with any password replaced by ``***``, safe to show.

    The query string and fragment are left out, because a driver can read
    credentials from them. A URI that is not a string, such as
    Elasticsearch's dict of hosts, is replaced as a whole, because its
    credentials can sit anywhere in it.
    """
    if not isinstance(uri, str):
        return "<not shown>"
    scheme, separator, rest = uri.partition("://")
    if not separator:
        return "<not shown>"
    # A password can hold "/", "?" or "#", so the userinfo is read before
    # the query is cut. The username holds none of ":", "/" or "@", so an
    # "@" inside the query, as in "?password=a@b", is not read as userinfo.
    # The password runs to its first "@", then on to each later "@" that no
    # "/", "?" or "#" comes before, so an "@" in the password is kept out of
    # the host and an "@" in the path or query is kept out of the password.
    userinfo = re.match(r"([^:/@]*)(:[^@]*(?:@[^@/?#]*)*)?@", rest)
    location = rest[userinfo.end() :] if userinfo else rest
    location = re.split(r"[?#]", location, maxsplit=1)[0]
    if not userinfo:
        return f"{scheme}://{location}"
    username, password = userinfo.groups()
    return f"{scheme}://{username}{':***' if password is not None else ''}@{location}"


def _known_database_types() -> set[str]:
    """Return the database types a repository or database model may name.

    The set holds the ``database_type`` of every adapter in the databases
    registry. Two kinds of adapter count under their name instead, because
    their ``database_type`` cannot be read: a registered adapter that fails to
    load or to pass the registry's checks, and an entry point in the
    ``protean.databases`` group that registered nothing, as the built-in
    SQLAlchemy and Elasticsearch adapters do when their extra is not
    installed. Each built-in adapter's name equals its ``database_type``.
    """
    # ``list()`` does not load entry points, and this check can run before
    # any ``get()`` has loaded them.
    database_registry._discover_plugins()
    registered = database_registry.list()
    known = {
        entry_point.name
        for entry_point in metadata.entry_points().select(group=database_registry.group)
        if entry_point.name not in registered
    }
    for name in registered:
        try:
            database_type = database_registry.get(name).database_type
        except Exception:  # noqa: BLE001 - an adapter is third-party code
            database_type = None
        known.add(database_type if isinstance(database_type, str) else name)
    return known


def _wildcard_database_type(element_cls: type[Any]) -> str | None:
    """Return the ``database_type`` that makes ``element_cls`` serve every database."""
    return "ALL" if element_cls.element_type == DomainObjects.REPOSITORY else None


def _accepted_database_types(element_cls: type[Any], known: set[str]) -> str:
    """Return the sentence that lists the values ``element_cls`` may declare."""
    types = ", ".join(sorted(known)) or "none, because no adapter is registered"
    if element_cls.element_type == DomainObjects.REPOSITORY:
        return f"Use `ALL` or one of: {types}"
    return f"Leave it unset or use one of: {types}"


class Databases(collections.abc.MutableMapping[str, BaseDatabase]):
    def __init__(self, domain: "Domain") -> None:
        self.domain = domain
        self._databases: dict[str, BaseDatabase] | None = None

        # Recognized Repositories are memoized within providers
        # for subsequent calls. The outer key is the aggregate's fully
        # qualified name, such as 'app.User'. The inner key is a database
        # type, such as 'postgresql', or 'ALL' for a repository that serves
        # every database.
        self._repositories: dict[str, dict[str, type[BaseRepository]]] = defaultdict(
            dict
        )

    def __getitem__(self, key: str) -> BaseDatabase:
        if not self._databases:
            raise KeyError(key)
        return self._databases[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._databases) if self._databases else iter({})

    def __len__(self) -> int:
        return len(self._databases) if self._databases else 0

    def __setitem__(self, key: str, value: BaseDatabase) -> None:
        if self._databases is None:
            self._databases = {}

        self._databases[key] = value

    def __delitem__(self, key: str) -> None:
        if not self._databases:
            raise KeyError(key)
        del self._databases[key]

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
        # When explicitly provided, `database_type` names the database type in
        # use and locks the repository to it: a repository registered with
        # `@domain.repository(part_of=Post, database_type="postgresql")` is used
        # only when the provider is PostgreSQL.
        #
        # In the absence of an explicit database type, the repository is
        # associated with "ALL" and is used for all databases.
        database = repository_cls.meta_.database_type

        aggregate_name = _fully_qualified_name(part_of)

        self._repositories[aggregate_name][database] = repository_cls

    def close(self) -> None:
        """Close all provider connections and release resources."""
        if self._databases:
            for name, provider in self._databases.items():
                try:
                    provider.close()
                except Exception:  # one failing provider must not stop closing the rest
                    logger.exception("Error closing provider '%s'", name)
            logger.debug("All providers closed")

    def _initialize(self, connect: bool = True) -> None:
        """Read config file and initialize providers.

        Each provider is checked with ``ping`` unless ``connect`` is False.
        """
        # Close existing providers before re-initializing to prevent
        # connection leaks (e.g., when domain.init() is called again).
        self.close()

        configured_providers = self.domain.config["databases"]
        provider_objects: dict[str, BaseDatabase] = {}

        if configured_providers and isinstance(configured_providers, dict):
            if "default" not in configured_providers:
                raise ConfigurationError("You must define a 'default' provider")

            for provider_name, config in configured_providers.items():
                provider_type = config.get("provider")
                provider_cls = database_registry.get(provider_type)
                provider = provider_cls(provider_name, self.domain, config)

                # Initialize a connection to check if everything is ok
                if connect and not provider.ping():
                    raise ConfigurationError(
                        "Could not connect to database at "
                        f"{_without_password(config['database_uri'])}"
                    )

                provider_objects[provider_name] = provider

        self._databases = provider_objects

    def validate_identity_capacity(self) -> None:
        """Refuse an identity a SQL provider cannot store.

        Runs ``_refuse_unstorable_identity`` for every aggregate, entity and
        projection whose provider is a SQLAlchemy provider. Models are built
        lazily, so this makes ``Domain.init()`` report the problem before the
        first repository call does.

        Raises:
            ConfigurationError: An element on a SQLAlchemy provider would get
                an identity its column cannot hold.
        """
        try:
            # SQLAlchemy is an optional extra; without it no SQL provider exists.
            from protean.adapters.database.sqlalchemy import (  # noqa: PLC0415
                SADatabase,
                _refuse_unstorable_identity,
            )
        except ImportError:  # pragma: no cover - sqlalchemy backs every SADatabase
            return

        providers = self._databases or {}
        registry = self.domain.registry
        for records in (registry.aggregates, registry.entities, registry.projections):
            for record in records.values():
                provider = providers.get(record.cls.meta_.database)
                if isinstance(provider, SADatabase):
                    _refuse_unstorable_identity(record.cls, provider)

    def validate_database_types(
        self, elements: Iterable[type[Any]] | None = None
    ) -> None:
        """Refuse a repository or database model bound to an unknown database type.

        A repository may declare ``database_type="ALL"`` and a database model
        may leave it as ``None``. Any other value must be a string equal to
        the ``database_type`` of an adapter in the databases registry.

        Args:
            elements: The repositories and database models to check. Defaults
                to every one registered with the domain.

        Raises:
            ConfigurationError: A repository or database model declares a
                ``database_type`` that no registered adapter provides.
        """
        if elements is None:
            registry = self.domain.registry
            elements = [
                record.cls
                for records in (registry.repositories, registry.database_models)
                for record in records.values()
            ]
        unchecked = [
            element_cls
            for element_cls in elements
            if element_cls.meta_.database_type != _wildcard_database_type(element_cls)
        ]
        if not unchecked:
            return

        known = _known_database_types()
        for element_cls in unchecked:
            database_type = element_cls.meta_.database_type
            if not isinstance(database_type, str) or database_type not in known:
                raise ConfigurationError(
                    f"`{element_cls.__name__}` declares database_type "
                    f"`{database_type}`, which no registered database adapter "
                    f"provides. {_accepted_database_types(element_cls, known)}"
                )

    def get_connection(self, provider_name: str = "default") -> Any:
        """Fetch connection from Provider"""
        if self._databases is None:
            self._initialize()

        assert self._databases is not None

        if provider_name not in self._databases:
            configured = sorted(self._databases.keys()) if self._databases else []
            raise ConfigurationError(
                f"No provider configured with name '{provider_name}'. "
                f"Configured providers: {', '.join(configured) or 'none'}"
            )
        return self._databases[provider_name].get_connection()

    def repository_for(self, part_of: type["OptionsMixin"]) -> BaseRepository:
        """Retrieve a Repository registered for the Aggregate"""
        if self._databases is None:
            self._initialize()

        provider_name = part_of.meta_.database
        assert self._databases is not None

        if provider_name not in self._databases:
            configured = sorted(self._databases.keys()) if self._databases else []
            raise ConfigurationError(
                f"No provider configured with name '{provider_name}'. "
                f"Configured providers: {', '.join(configured) or 'none'}"
            )
        provider = self._databases[provider_name]
        database = provider.database_type

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
