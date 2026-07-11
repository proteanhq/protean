"""Test domain whose only warning has a domain-scoped (non-class) element.

``OrderPlaced`` is ``published=True`` but the domain configures no external
brokers, so ``PUBLISHED_NO_EXTERNAL_BROKER`` fires with ``element`` set to the
domain name — which is not a registered class FQN and therefore does not resolve
to a source file. Used by ``tests/cli/test_check.py`` to exercise the
location-less diagnostic path (SARIF ``locations: []`` / annotation with no
``file=``).
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST39")


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.event(part_of=Order, published=True)
class OrderPlaced:
    name = String()
