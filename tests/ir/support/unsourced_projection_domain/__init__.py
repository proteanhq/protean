"""Real-source corpus for the UNSOURCED_PROJECTION_FIELD diagnostic tests.

The rule reads projector method bodies through the behavioral substrate, so the
projections and projectors it inspects must live in a real, importable module (a
class defined inside a test function has a ``<locals>`` qualname the element
index cannot pin). The consuming test registers
:mod:`~tests.ir.support.unsourced_projection_domain.catalog` as a real domain
and builds the IR once.
"""
