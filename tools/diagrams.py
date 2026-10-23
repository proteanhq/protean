"""Render every Mermaid diagram in the docs to a pair of SVGs, one per theme.

Mermaid bakes its colours into the SVG at render time, so a diagram drawn in
the browser cannot follow the palette toggle. Drawing them here instead gives
each diagram a light and a dark file, and the stylesheet shows the one that
matches the scheme. The build then needs no diagram JavaScript at all.

A diagram is named by the SHA-256 of its source, so an unchanged diagram is
never redrawn and the rendered files can be committed. Run this after editing
any ```mermaid block:

    python3 tools/diagrams.py            # render what is missing
    python3 tools/diagrams.py --force    # redraw everything
    python3 tools/diagrams.py --prune    # also delete files no diagram claims

It needs Node. Chrome is reused through PUPPETEER_EXECUTABLE_PATH when it is
installed in the usual place, which saves mermaid-cli downloading its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "assets" / "diagrams"
MMDC = "@mermaid-js/mermaid-cli@11.4.2"

FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```mermaid[ \t]*\n(?P<body>.*?)^(?P=indent)```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

# The values are the Protean tokens, the same ones docs/stylesheets/extra.css
# carries. Keep the two in step when a token changes.
THEMES = {
    "light": {
        "primaryColor": "#FBF9F4",  # paper
        "primaryTextColor": "#1A1512",  # text
        "primaryBorderColor": "#EE4326",  # brand
        "secondaryColor": "#F5F2EB",  # calloutBg
        "tertiaryColor": "#FBF9F4",
        "background": "#FBF9F4",
        "mainBkg": "#FBF9F4",
        "lineColor": "#6A625A",
        "textColor": "#4A4239",  # textBody
        "signalColor": "#6A625A",
        "signalTextColor": "#4A4239",
        "labelBoxBkgColor": "#FBF9F4",
        "labelBoxBorderColor": "#E7E0D3",
        "labelTextColor": "#1A1512",
        "loopTextColor": "#4A4239",
        "noteBkgColor": "#F5F2EB",
        "noteTextColor": "#1A1512",
        "noteBorderColor": "#E7E0D3",
        "actorBkg": "#FBF9F4",
        "actorBorder": "#6F675E",  # text3
        "actorTextColor": "#1A1512",
        "actorLineColor": "#A99F92",
        "activationBkgColor": "#F5F2EB",
        "activationBorderColor": "#E7E0D3",
        "sequenceNumberColor": "#FBF9F4",
    },
    "dark": {
        "primaryColor": "#0C0F11",  # paper, dark
        "primaryTextColor": "#F3F1EE",
        "primaryBorderColor": "#FF5136",
        "secondaryColor": "#11161A",
        "tertiaryColor": "#0C0F11",
        "background": "#0C0F11",
        "mainBkg": "#0C0F11",
        "lineColor": "#9BA3AB",
        "textColor": "#B8BEC4",
        "signalColor": "#9BA3AB",
        "signalTextColor": "#B8BEC4",
        "labelBoxBkgColor": "#0C0F11",
        "labelBoxBorderColor": "#262D33",
        "labelTextColor": "#F3F1EE",
        "loopTextColor": "#B8BEC4",
        "noteBkgColor": "#11161A",
        "noteTextColor": "#F3F1EE",
        "noteBorderColor": "#262D33",
        "actorBkg": "#0C0F11",
        "actorBorder": "#9BA3AB",
        "actorTextColor": "#F3F1EE",
        "actorLineColor": "#3A424A",
        "activationBkgColor": "#11161A",
        "activationBorderColor": "#262D33",
        "sequenceNumberColor": "#0C0F11",
    },
}

COMMON = {
    "fontFamily": "Hanken Grotesk, system-ui, -apple-system, sans-serif",
    "fontSize": "14px",
}


def digest(source: str) -> str:
    return hashlib.sha256(source.strip().encode("utf-8")).hexdigest()[:16]


def sources() -> dict[str, str]:
    """Every distinct diagram in the docs, by its digest."""
    found: dict[str, str] = {}
    for md in sorted(DOCS.rglob("*.md")):
        for m in FENCE.finditer(md.read_text(encoding="utf-8")):
            indent = m.group("indent")
            body = m.group("body")
            if indent:
                body = "\n".join(line.removeprefix(indent) for line in body.split("\n"))
            body = body.strip()
            if body:
                found[digest(body)] = body
    return found


def config(theme: str) -> dict:
    variables = dict(THEMES[theme])
    variables.update(COMMON)
    return {
        "theme": "base",
        "themeVariables": variables,
        # A diagram keeps the size it is drawn at; the stylesheet scrolls it
        # sideways when it outgrows the column, the way a code block does.
        # Scaling to fit shrinks the labels with it.
        "sequence": {"useMaxWidth": False, "showSequenceNumbers": True},
        "flowchart": {"useMaxWidth": False},
    }


def render(source: str, theme: str, target: Path, work: Path) -> None:
    src = work / "diagram.mmd"
    src.write_text(source + "\n", encoding="utf-8")
    cfg = work / f"{theme}.json"
    cfg.write_text(json.dumps(config(theme)), encoding="utf-8")

    env = dict(os.environ)
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(chrome).exists():
        env.setdefault("PUPPETEER_EXECUTABLE_PATH", chrome)

    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "npx",
            "-y",
            MMDC,
            "-i",
            str(src),
            "-o",
            str(target),
            "-c",
            str(cfg),
            "-b",
            "transparent",
            "-q",
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )

    # mermaid-cli ends the file at the closing tag. The repo's end-of-file-fixer
    # hook then appends a newline, so without this every rendered file comes
    # back modified on the next run.
    art = target.read_bytes()
    if not art.endswith(b"\n"):
        target.write_bytes(art + b"\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force", action="store_true", help="redraw diagrams that already exist"
    )
    ap.add_argument(
        "--prune", action="store_true", help="delete rendered files no diagram claims"
    )
    args = ap.parse_args()

    found = sources()
    print(f"{len(found)} distinct diagrams in {DOCS.relative_to(ROOT)}")

    todo = [
        (key, theme)
        for key in sorted(found)
        for theme in ("light", "dark")
        if args.force or not (OUT / f"{key}-{theme}.svg").exists()
    ]
    if not todo:
        print("every diagram is already rendered")
    else:
        print(f"rendering {len(todo)} file(s)")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for n, (key, theme) in enumerate(todo, 1):
            target = OUT / f"{key}-{theme}.svg"
            try:
                render(found[key], theme, target, work)
            except subprocess.CalledProcessError as exc:
                print(f"  [{n}/{len(todo)}] FAILED {target.name}")
                print((exc.stderr or exc.stdout or "").strip()[:600])
                return 1
            print(f"  [{n}/{len(todo)}] {target.name}  {target.stat().st_size} bytes")

    if args.prune:
        keep = {f"{k}-{t}.svg" for k in found for t in ("light", "dark")}
        for stale in sorted(OUT.glob("*.svg")):
            if stale.name not in keep:
                stale.unlink()
                print(f"  removed {stale.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
