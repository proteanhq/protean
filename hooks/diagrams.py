"""Swap each ```mermaid block for the pair of SVGs rendered by tools/diagrams.py.

The Markdown keeps the diagram source, which is where an author expects to edit
it. The build replaces the block with two images, one per theme, and the
stylesheet shows the one that matches the scheme. No diagram JavaScript runs in
the browser, so a palette toggle repaints a diagram the way it repaints
anything else.

A diagram is named by the SHA-256 of its source. When a block has no rendered
pair, the block is left as it is and the page logs which file to run:

    python3 tools/diagrams.py
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

LOG = logging.getLogger("mkdocs.hooks.diagrams")

FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```mermaid[ \t]*\n(?P<body>.*?)^(?P=indent)```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

RENDERED = Path(__file__).resolve().parent.parent / "docs" / "assets" / "diagrams"

missing: set[str] = set()


def digest(source: str) -> str:
    return hashlib.sha256(source.strip().encode("utf-8")).hexdigest()[:16]


KINDS = {
    "sequencediagram": "Sequence diagram",
    "flowchart": "Flowchart",
    "graph": "Flowchart",
    "statediagram-v2": "State diagram",
    "statediagram": "State diagram",
    "classdiagram": "Class diagram",
    "erdiagram": "Entity relationship diagram",
}


def describe(source: str) -> str:
    """Alt text a screen reader can use.

    The first line of a diagram is its keyword, so using it raw announced the
    picture as "sequenceDiagram". A Mermaid title, when the author wrote one,
    says what the diagram is about, so it is preferred.
    """
    first = source.split("\n", 1)[0].strip().split()
    kind = KINDS.get(first[0].lower() if first else "", "Diagram")
    for line in source.split("\n"):
        line = line.strip()
        if line.lower().startswith("title "):
            return f"{kind}: {line[6:].strip()}".replace('"', "'")
    return kind


def on_page_markdown(markdown: str, page, config, files):
    def swap(match: re.Match[str]) -> str:
        indent = match.group("indent")
        body = match.group("body")
        if indent:
            body = "\n".join(line.removeprefix(indent) for line in body.split("\n"))
        body = body.strip()
        if not body:
            return match.group(0)

        key = digest(body)
        if not (RENDERED / f"{key}-light.svg").exists():
            missing.add(f"{page.file.src_uri}: {key}")
            return match.group(0)

        # With directory URLs a page at a/b/c.md is served from a/b/c/, so the
        # depth that matters is the URL's, never the source path's.
        base = "/".join([".."] * page.file.url.count("/")) or "."
        alt = describe(body)
        return (
            f'{indent}<p class="pt-diagram">'
            f'<img class="pt-diagram__art pt-diagram__art--light" '
            f'src="{base}/assets/diagrams/{key}-light.svg" alt="{alt}" loading="lazy">'
            f'<img class="pt-diagram__art pt-diagram__art--dark" '
            f'src="{base}/assets/diagrams/{key}-dark.svg" alt="" aria-hidden="true" loading="lazy">'
            f"</p>"
        )

    return FENCE.sub(swap, markdown)


def on_post_build(config):
    if missing:
        LOG.warning(
            "%d diagram(s) have no rendered SVG and were left as source. "
            "Run: python3 tools/diagrams.py\n  %s",
            len(missing),
            "\n  ".join(sorted(missing)),
        )
