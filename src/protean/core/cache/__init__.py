"""Package for defining interfaces for Cache Backend Implementations"""

# Local/Relative Imports
from .base import DEFAULT_EXPIRY, BaseCache
from .wrapper import cache

__all__ = ('BaseCache', 'DEFAULT_EXPIRY', 'cache')
