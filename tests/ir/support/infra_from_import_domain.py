"""Fixture module using the ``from protean import adapters`` import form.

For an ``ast.ImportFrom`` the rule must inspect the imported *alias* names
(``protean`` + ``.adapters``), not only ``node.module`` (``protean``), or this
evasion form slips past the ``protean.adapters`` match that catches the dotted
``import protean.adapters`` and ``from protean.adapters.x import Y`` forms.
"""

from protean import adapters  # noqa: F401
from protean.core.aggregate import BaseAggregate
from protean.fields import String


class FromFormOrder(BaseAggregate):
    name = String(max_length=50)
