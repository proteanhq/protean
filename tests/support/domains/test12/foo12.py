"""Dummy Domain file to test auto loading of `subdomain` attribute"""

from protean.domain import Domain

subdomain = Domain(__file__, "TEST12", load_toml=False)
specific = Domain(__file__, "TEST12_SPECIFIC", load_toml=False)
