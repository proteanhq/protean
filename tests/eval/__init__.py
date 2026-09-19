"""Comparison-eval harness.

This package holds the eval machinery that runs a scaffolding task through the
context-driven path, records it as a replayable fixture, and scores both
approaches against a deterministic gold. It is test-and-eval infrastructure,
kept out of the shipped wheel (the wheel packages only ``src/protean``).

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

The scoring pieces:

- :mod:`tests.eval.discovery`: the shared subprocess setup (env-strip and domain
  discovery) that ``run_verify`` and ``build_ir`` both use, plus the import
  package the scorer reads a project's bounded-context segments against.
- :mod:`tests.eval.ir_probe`: ``build_ir``, which reads a produced project's IR
  by shelling ``protean ir show`` into it.
- :mod:`tests.eval.spec`: the per-task sidecar ``spec.json`` (the gold recipe)
  and the task-discovery helper.
- :mod:`tests.eval.gold`: ``build_gold``, which scaffolds a task's deterministic
  gold project from its spec and reads back its IR.
- :mod:`tests.eval.scoring`: the per-element rubric that scores a produced IR
  against the gold's, plus ``score_boundary``, the boundary/aggregate recovery
  layer (placement and context).
- :mod:`tests.eval.compare`: ``compare``, which runs both approaches over a task
  and reports each one's verify-green, correctness, and boundary recovery.
"""
