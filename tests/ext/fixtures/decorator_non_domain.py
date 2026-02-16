"""Fixture: non-Domain object with aggregate() method should NOT inject base classes.

This tests lines 204-209 of mypy_plugin.py: when a decorator receiver
resolves to a type that is NOT protean.domain.Domain, the plugin skips
base class injection.
"""


class NotDomain:
    """A regular class that happens to have an 'aggregate' method."""

    def aggregate(self, cls):
        return cls


not_domain = NotDomain()


@not_domain.aggregate
class FakeAggregate:
    name: str = "hello"


# This should NOT have BaseAggregate methods injected
obj = FakeAggregate()
reveal_type(obj.name)  # E: Revealed type is "builtins.str"
# obj.to_dict  would be an error if plugin incorrectly injected base
# obj.raise_   would be an error if plugin incorrectly injected base
