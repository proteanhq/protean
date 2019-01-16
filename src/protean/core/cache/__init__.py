"""Package for defining interfaces for Cache Backend Implementations"""

from .base import DEFAULT_EXPIRY
from .base import BaseCache
from .wrapper import cache

__all__ = ('BaseCache', 'DEFAULT_EXPIRY', 'cache')
