"""A helper module of the domain package that registers no element.

Whole-package parse scope means this module's classes are indexed anyway, with
no role tags — an element-driven walk would miss them entirely.
"""


class LabelFormatter:
    """Not a domain element; a plain collaborator."""

    def format(self, label: str) -> str:
        return label.strip()

    def _pad(self, label: str) -> str:
        return f" {label} "
