"""
Protean Server module
"""

from .engine import Engine

try:
    from protean.server.fastapi_server import FastAPIServer

    __all__ = ["Engine", "FastAPIServer"]
except ImportError:
    # FastAPI is an optional dependency
    __all__ = ["Engine"]
