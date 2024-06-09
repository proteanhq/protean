"""Dummy Domain file to test auto loading of `domain` attribute
when no file/package and attribute name were provided
"""

from protean.domain import Domain

domain = Domain(__file__, "TEST10", load_toml=False)
