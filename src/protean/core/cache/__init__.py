"""Package for defining interfaces for Cache Backend Implementations"""

from .base import BaseCache, DEFAULT_EXPIRY
from .wrapper import cache

__all__ = ('BaseCache', 'DEFAULT_EXPIRY', 'cache')
