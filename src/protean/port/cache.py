from abc import ABCMeta, abstractmethod
from typing import Optional, Union

from protean.core.projection import BaseProjection
from protean.utils.inflection import underscore


class BaseCache(metaclass=ABCMeta):
    def __init__(self, name, domain, conn_info: dict):
        """Initialize Cache with Connection/Adapter details"""
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

        # Default TTL: 300 seconds
        self.ttl = conn_info.get("TTL", 300)

        # Temporary cache of projections
        self._projections = {}

    def register_projection(self, projection_cls):
        """Registers a projection object for data serialization and de-serialization"""
        projection_name = underscore(projection_cls.__name__)
        self._projections[projection_name] = projection_cls

    @abstractmethod
    def ping(self):
        """Healthcheck to verify cache is active and accessible"""

    @abstractmethod
    def get_connection(self):
        """Get the connection object for the cache"""

    @abstractmethod
    def add(
        self, projection: BaseProjection, ttl: Optional[Union[int, float]] = None
    ) -> None:
        """Add projection record to cache

        KEY: Projection ID
        Value: Projection Data (derived from `to_dict()`)

        TTL is in seconds. If not specified explicitly in method call,
        it can be picked up from broker configuration. In the absence of
        configuration, it can be defaulted to an optimum value, say 300 seconds.

        Args:
            projection (BaseProjection): Projection Instance containing data
            ttl (int, float, optional): Timeout in seconds. Defaults to None.
        """

    @abstractmethod
    def get(self, key):
        """Retrieve data by key"""

    @abstractmethod
    def get_all(self, key_pattern, last_position=0, size=25):
        """Retrieve data by key pattern"""

    @abstractmethod
    def count(self, key_pattern):
        """Retrieve count of data by key pattern"""

    @abstractmethod
    def remove(self, projection):
        """Remove a cache record by projection object"""

    @abstractmethod
    def remove_by_key(self, key):
        """Remove a cache record by key"""

    @abstractmethod
    def remove_by_key_pattern(self, key_pattern):
        """Remove a cache record by key pattern"""

    @abstractmethod
    def flush_all(self):
        """Remove all entries in Cache"""

    @abstractmethod
    def set_ttl(self, key, ttl):
        """Set a TTL explicitly on a key"""

    @abstractmethod
    def get_ttl(self, key):
        """Get the TTL set on a key"""
