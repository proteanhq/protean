"""Base utilities for IR-powered documentation generators.

This module provides shared helpers used by all documentation generators:

- **Mermaid helpers**: escape text for Mermaid diagram labels, wrap output
  in fenced code blocks.
- **Name helpers**: shorten fully-qualified names, format field type strings
  for display.
"""

from __future__ import annotations

import re
from typing import Any

# Characters that have syntactic meaning in Mermaid and must be escaped
# or quoted inside node labels and edge labels.
_MERMAID_SPECIAL = re.compile(r'([|{}\[\]()<>#"&])')


def mermaid_escape(text: str) -> str:
    """Escape characters that have syntactic meaning in Mermaid diagrams.

    Mermaid uses ``|``, ``{}``, ``[]``, ``()``, ``<>``, ``#``, ``"``, and
    ``&`` as delimiters in node shapes, edge labels, and entity names.
    This function wraps the text in double-quotes to safely embed
    arbitrary strings in Mermaid labels.

    If the text is empty it is returned as-is (quoting an empty string
    produces ``""`` which Mermaid renders as a visible empty node).

    Examples::

        >>> mermaid_escape("Order")
        'Order'
        >>> mermaid_escape("dict[str, int]")
        '"dict[str, int]"'
        >>> mermaid_escape("")
        ''
    """
    if not text:
        return text
    if _MERMAID_SPECIAL.search(text):
        # Double-quoting is the Mermaid-recommended way to include
        # special characters in labels.
        escaped = text.replace('"', "#quot;")
        return f'"{escaped}"'
    return text


def mermaid_fence(body: str, *, title: str = "") -> str:
    """Wrap *body* in a Markdown fenced code block with ``mermaid`` language tag.

    An optional *title* is prepended as a Markdown heading before the fence.

    Examples::

        >>> print(mermaid_fence("graph LR\\n  A --> B"))
        ```mermaid
        graph LR
          A --> B
        ```
    """
    parts: list[str] = []
    if title:
        parts.append(f"## {title}\n")
    parts.append("```mermaid")
    parts.append(body)
    parts.append("```")
    return "\n".join(parts)


def short_name(fqn: str) -> str:
    """Extract the short class name from a fully-qualified name.

    Examples::

        >>> short_name("ecommerce.ordering.Order")
        'Order'
        >>> short_name("Order")
        'Order'
        >>> short_name("")
        ''
    """
    if not fqn:
        return fqn
    return fqn.rsplit(".", 1)[-1]


def module_path(fqn: str) -> str:
    """Extract the module path from a fully-qualified name.

    Returns everything before the last dot.  If there is no dot the
    empty string is returned.

    Examples::

        >>> module_path("ecommerce.ordering.Order")
        'ecommerce.ordering'
        >>> module_path("Order")
        ''
    """
    if "." not in fqn:
        return ""
    return fqn.rsplit(".", 1)[0]


def field_type_label(field: dict[str, Any]) -> str:
    """Build a human-readable type label for an IR field dict.

    The label format depends on the field kind:

    - ``auto`` → ``"Auto"``
    - ``standard`` → the type name (e.g. ``"String"``, ``"Integer"``)
    - ``list`` → ``"List[ContentType]"`` or ``"List"``
    - ``dict`` → ``"Dict"``
    - ``value_object`` / ``has_one`` / ``has_many`` / ``reference``
      → the short name of the target (e.g. ``"Address"``)
    - ``value_object_list`` → ``"List[TargetName]"``

    Examples::

        >>> field_type_label({"kind": "standard", "type": "String"})
        'String'
        >>> field_type_label({"kind": "has_many", "target": "app.OrderItem"})
        'OrderItem[]'
        >>> field_type_label({"kind": "list", "type": "List", "content_type": "String"})
        'List[String]'
        >>> field_type_label({"kind": "value_object", "target": "app.Address"})
        'Address'
    """
    kind = field.get("kind", "standard")

    if kind == "auto":
        return "Auto"

    if kind in ("value_object", "has_one", "reference"):
        target = field.get("target", "")
        return short_name(target) if target else kind

    if kind == "has_many":
        target = field.get("target", "")
        name = short_name(target) if target else "?"
        return f"{name}[]"

    if kind == "value_object_list":
        target = field.get("target", "")
        name = short_name(target) if target else "?"
        return f"List[{name}]"

    if kind == "list":
        content = field.get("content_type", "")
        return f"List[{content}]" if content else "List"

    if kind == "dict":
        return "Dict"

    # standard / fallback
    return field.get("type", "?")


def field_summary(field: dict[str, Any]) -> str:
    """Build a compact summary string for an IR field.

    Combines the type label with key constraints (required, identifier,
    unique) in a parenthesised suffix.

    Examples::

        >>> field_summary({"kind": "standard", "type": "String", "required": True})
        'String (required)'
        >>> field_summary({"kind": "auto", "identifier": True})
        'Auto (identifier)'
        >>> field_summary({"kind": "standard", "type": "Integer"})
        'Integer'
    """
    label = field_type_label(field)
    tags: list[str] = []
    if field.get("identifier"):
        tags.append("identifier")
    if field.get("required") and not field.get("identifier"):
        tags.append("required")
    if field.get("unique") and not field.get("identifier"):
        tags.append("unique")
    if tags:
        return f"{label} ({', '.join(tags)})"
    return label


def sanitize_mermaid_id(text: str) -> str:
    """Turn an arbitrary string into a valid Mermaid node identifier.

    Mermaid node IDs must be alphanumeric (plus underscores).  This
    function replaces dots and other non-word characters with
    underscores.

    Examples::

        >>> sanitize_mermaid_id("ecommerce.ordering.Order")
        'ecommerce_ordering_Order'
        >>> sanitize_mermaid_id("Order")
        'Order'
    """
    return re.sub(r"\W+", "_", text).strip("_")
