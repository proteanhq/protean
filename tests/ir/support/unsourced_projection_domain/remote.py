"""A projection that ``catalog.LocalImportProjector`` imports inside its handler.

It lives outside ``catalog`` so that no module-level name in ``catalog`` can
resolve it.
"""

from protean.core.projection import BaseProjection
from protean.fields import Identifier, String


class RemoteProjection(BaseProjection):
    key = Identifier(identifier=True)
    headline = String(max_length=50)
    byline = String(max_length=50)
