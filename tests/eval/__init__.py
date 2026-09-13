"""Comparison-eval harness.

This package holds the eval machinery that runs a scaffolding task through the
context-driven path and records it as a replayable fixture. It is test-and-eval
infrastructure, kept out of the shipped wheel (the wheel packages only
``src/protean``).

The pieces:

- :mod:`tests.eval.workspace`: a sandbox directory the agent writes a project
  into, plus a stable hash of the files it produced.
- :mod:`tests.eval.tools`: the tools the agent drives: ``write_file``,
  ``read_file``, ``list_dir``, and ``run_verify`` (which runs ``protean verify``
  and returns its verdict as the agent's feedback signal).
- :mod:`tests.eval.drivers`: the thing that produces assistant turns. A
  :class:`~tests.eval.drivers.ReplayDriver` replays recorded turns with no model
  (the CI lane); a live driver is resolved at runtime and calls a real model
  (the opt-in, maintainer-side lane that doubles as the recorder).
- :mod:`tests.eval.transcript`: the provider-neutral record/replay format,
  one JSON file per run keyed to the pack version.
- :mod:`tests.eval.runner`: the multi-turn loop that ties them together, plus
  ``record`` (live) and ``replay`` (deterministic).

Scoring lives with the comparison eval that consumes these transcripts. This
package produces and records a project; it does not score it.
"""
