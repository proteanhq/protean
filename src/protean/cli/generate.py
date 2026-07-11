"""Reserved namespace for Protean's CLI code generators.

The original ``generate docker-compose`` command was a no-op stub — it wrote no
file and ended at a ``# FIXME`` — so it was removed outright during the 1.0 CLI
surface consolidation rather than carried through a deprecation cycle.
Real Dockerfile/compose generation is tracked separately.

This module is intentionally kept as the future home of the ``generate`` command
group, but exposes **no commands** and is **not** registered on the top-level
``protean`` app while it is empty. Once a concrete generator lands it can
be reintroduced here and wired into ``protean.cli`` without re-plumbing anything.
Keeping the module inert (rather than deleting it) avoids churning the CLI
package layout for a namespace that is coming back.
"""
