"""Reserved namespace for Protean's CLI code generators.

This module is intentionally kept as the future home of the ``generate`` command
group, but exposes **no commands** and is **not** registered on the top-level
``protean`` app while it is empty. Once a concrete generator lands it can
be reintroduced here and wired into ``protean.cli`` without re-plumbing anything.
Keeping the module inert (rather than deleting it) avoids churning the CLI
package layout for a namespace that is coming back.
"""
