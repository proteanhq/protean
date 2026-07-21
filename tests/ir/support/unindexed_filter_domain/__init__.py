"""Real-source corpus for the UNINDEXED_FILTER_PATH diagnostic tests.

The rule reads method bodies through the behavioral substrate, so the aggregates,
repositories, and application service it flags must live in a real, importable
module (a class defined inside a test function has a ``<locals>`` qualname the
element index cannot pin). The consuming test registers subsets of
:mod:`~tests.ir.support.unindexed_filter_domain.catalog` as real domains and
attaches the indexes each scenario needs at registration time.
"""
