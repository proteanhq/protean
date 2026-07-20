"""Static-analysis substrate for ``protean check``.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir`` —
the modules in this package are the shared machinery that IR diagnostic rules
build on, not a public surface.
"""

from __future__ import annotations

from protean.ir.analysis.source_provider import SourceProvider

__all__ = ["SourceProvider"]
