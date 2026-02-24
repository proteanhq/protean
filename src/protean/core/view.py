"""Read-only facade for querying projections.

``ReadView`` wraps the underlying repository (database-backed) or cache
(cache-backed) and exposes only read operations.  Obtain an instance via
``domain.view_for(ProjectionClass)``.
"""

import logging
from typing import TYPE_CHECKING, Any

from protean.exceptions import NotSupportedError, ObjectNotFoundError
from protean.utils.inflection import underscore

if TYPE_CHECKING:
    from protean.core.projection import BaseProjection
    from protean.core.queryset import ReadOnlyQuerySet
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class ReadView:
    """Read-only facade for querying projections.

    Exposes ``get()``, ``query`` (``ReadOnlyQuerySet``), ``find_by()``,
    ``count()``, and ``exists()`` — but no ``add()``, ``update()``,
    ``delete()``, or ``_dao`` access.

    For **database-backed** projections every method works.  For
    **cache-backed** projections only ``get()``, ``count()``, and
    ``exists()`` are available; ``query`` and ``find_by()`` raise
    ``NotSupportedError`` because cache stores are key-value backends
    and do not support field-based filtering.
    """

    def __init__(
        self,
        domain: "Domain",
        projection_cls: type["BaseProjection"],
    ) -> None:
        self._domain = domain
        self._projection_cls = projection_cls
        self._is_cache_backed: bool = bool(projection_cls.meta_.cache)

    def __repr__(self) -> str:  # pragma: no cover
        backend = "cache" if self._is_cache_backed else "database"
        return f"<ReadView for {self._projection_cls.__name__} ({backend})>"

    # ── Internal helpers ─────────────────────────────────────

    def _repo(self):
        """Return the repository for a database-backed projection."""
        return self._domain.providers.repository_for(self._projection_cls)

    def _cache(self):
        """Return the cache adapter for a cache-backed projection."""
        return self._domain.caches.cache_for(self._projection_cls)

    # ── Public read API ──────────────────────────────────────

    @property
    def query(self) -> "ReadOnlyQuerySet":
        """Return a ``ReadOnlyQuerySet`` for fluent filtering, ordering,
        and pagination.

        Only available for database-backed projections.  Cache-backed
        projections raise ``NotSupportedError``.
        """
        if self._is_cache_backed:
            raise NotSupportedError(
                f"Querying with filters is not supported for cache-backed "
                f"projection `{self._projection_cls.__name__}`. "
                f"Use get() for key-based lookups."
            )
        return self._domain.query_for(self._projection_cls)

    def get(self, identifier: Any) -> "BaseProjection":
        """Retrieve a single projection record by its identifier.

        Raises ``ObjectNotFoundError`` if the record does not exist.
        """
        if self._is_cache_backed:
            projection_name = underscore(self._projection_cls.__name__)
            key = f"{projection_name}:::{identifier}"
            result = self._cache().get(key)
            if result is None:
                raise ObjectNotFoundError(
                    f"`{self._projection_cls.__name__}` object with identifier "
                    f"{identifier} does not exist."
                )
            return result
        else:
            return self._repo()._dao.get(identifier)

    def find_by(self, **kwargs: Any) -> "BaseProjection":
        """Find a single projection record matching the given criteria.

        Returns exactly one record.  Raises ``ObjectNotFoundError`` if
        none match and ``TooManyObjectsError`` if more than one matches.

        Only available for database-backed projections.
        """
        if self._is_cache_backed:
            raise NotSupportedError(
                f"find_by() is not supported for cache-backed "
                f"projection `{self._projection_cls.__name__}`. "
                f"Use get() for key-based lookups."
            )
        return self._repo()._dao.find_by(**kwargs)

    def count(self) -> int:
        """Return the total number of projection records."""
        if self._is_cache_backed:
            projection_name = underscore(self._projection_cls.__name__)
            key_pattern = f"{projection_name}:::.*"
            return self._cache().count(key_pattern)
        else:
            return self._domain.query_for(self._projection_cls).all().total

    def exists(self, identifier: Any) -> bool:
        """Return ``True`` if a record with *identifier* exists."""
        try:
            self.get(identifier)
            return True
        except ObjectNotFoundError:
            return False
