"""Fixture module whose source uses deprecated import surfaces.

Exercises the DEPRECATED_IMPORT on-disk scan: the rule resolves a registered
element's ``module`` to this file, AST-parses it, and matches the deprecated
``Method`` / ``Nested`` serializer-field call sites and the deprecated
``protean.utils`` plumbing access below.

The deprecated call sites live inside a class body / function that is **never
executed at import**, so importing this fixture does not itself fire the runtime
``DeprecationWarning`` — only the static scan sees them. ``import protean.utils``
binds the module without triggering its ``__getattr__``; the deprecated name is
reached only through the attribute access inside ``_uses_deprecated_util``.
"""

import protean.utils
from protean.core.aggregate import BaseAggregate
from protean.fields import Method, Nested, String


class DeprecatedUsageOrder(BaseAggregate):
    """A plain registered aggregate so this module is scanned by the rule."""

    name = String(max_length=50)


class _LegacySerializer:
    """Never instantiated; present only so the AST scan sees deprecated
    serializer-field call sites without the module firing runtime warnings."""

    def fields(self) -> dict[str, object]:
        return {
            "full_name": Method("full_name"),
            "address": Nested("Address"),
        }


def _uses_deprecated_util() -> object:
    """Never called; a static ``protean.utils`` plumbing access for the scan."""
    return protean.utils.generate_identity()
