"""Test domain with a diagnostic code that repeats across two elements.

Both ``Order`` and ``Invoice`` are bare aggregates with no command handler and
no invariants, so ``AGGREGATE_WITHOUT_COMMAND_HANDLER`` and
``AGGREGATE_NO_INVARIANTS`` each fire twice — one per aggregate. Used by
``tests/cli/test_check.py`` to prove the SARIF/annotation emitters collapse a
repeated code to a single ``reportingDescriptor`` (first occurrence wins).
"""

from protean import Domain
from protean.fields import String

domain = Domain(name="TEST38")


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.aggregate
class Invoice:
    reference = String(max_length=100)
