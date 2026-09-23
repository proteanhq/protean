"""Render the packaged dx pack skills into a Claude Code plugin layout.

This is one more render target for the dx pack, the same family as the per-editor
renderers in :mod:`protean.dx.renderers`. Where those project the pack into a
project's own files, this one projects the packaged teaching skills at
``src/protean/dx/pack/skills/`` into a Claude Code plugin, and the plugin tree is
committed into this repository so the marketplace can serve it.

Two manifests frame the tree:

- ``.claude-plugin/marketplace.json`` at the repo root names the ``proteanhq``
  marketplace and lists one plugin, ``protean``, sourced from ``./plugins/protean``.
- ``plugins/protean/.claude-plugin/plugin.json`` names the plugin and stamps it
  with the framework version, so a consumer can tell which version's guidance the
  skills carry. :mod:`.bumpversion.toml` moves this version on a release, the same
  way it moves ``server.json``.

The pack stays the single source: each skill's subtree (``SKILL.md`` plus any
``assets/`` and ``references/``) is copied verbatim into ``plugins/protean/skills/``.
The Python ``__init__.py`` package markers the pack carries (it ships as package
data under ``src/protean``) are dropped, since they are not part of a skill.

The render is deterministic: skills come in sorted order and every file is copied
byte for byte, so the committed tree and a fresh render never disagree. A drift
test in ``tests/dx/`` re-renders for the installed version and asserts byte-exact
equality with the committed tree, and ``protean dx build-plugin --check`` is the
same guard on the command line.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from protean.dx.pack import SKILLS_DIR, iter_skills, pack_files

__all__ = [
    "MARKETPLACE_NAME",
    "MARKETPLACE_PATH",
    "PLUGIN_MANIFEST_PATH",
    "PLUGIN_NAME",
    "PLUGIN_ROOT",
    "PLUGIN_SKILLS_ROOT",
    "PLUGIN_SOURCE",
    "marketplace_manifest",
    "plugin_drift",
    "plugin_manifest",
    "render_plugin_files",
    "write_plugin",
]

# The marketplace and the plugin it lists. The marketplace name stays
# ``proteanhq`` (the name the existing marketplace already uses) and the plugin
# is ``protean``, sourced from the committed tree beside the manifest.
MARKETPLACE_NAME = "proteanhq"
PLUGIN_NAME = "protean"
PLUGIN_SOURCE = "./plugins/protean"

# Repo-relative POSIX paths of the committed manifests and the plugin roots. The
# renderer keys every file it produces by one of these, and the check reads them
# back to compare against a fresh render.
MARKETPLACE_PATH = ".claude-plugin/marketplace.json"
PLUGIN_ROOT = "plugins/protean"
PLUGIN_MANIFEST_PATH = f"{PLUGIN_ROOT}/.claude-plugin/plugin.json"
PLUGIN_SKILLS_ROOT = f"{PLUGIN_ROOT}/skills"

# The Python package marker the pack carries so it ships as package data. It is
# not part of a skill, so the plugin render drops every one.
_PACKAGE_MARKER = "__init__.py"

# The plain-language descriptions the manifests carry. This cut ships skills
# only: no commands, agents, or hooks, and the MCP registration stays with the
# ``.mcp.json`` renderer.
_MARKETPLACE_DESCRIPTION = "Official plugins for the Protean DDD framework"
_PLUGIN_DESCRIPTION = (
    "Teaching skills for the Protean DDD framework, matched to the installed "
    "framework version."
)

# The people behind the marketplace and the plugin. The marketplace carries an
# email owner; the plugin carries the author with the project URL.
_OWNER = {"name": "Protean HQ", "email": "hello@proteanhq.com"}
_AUTHOR = {"name": "Protean HQ", "url": "https://proteanhq.com"}


def marketplace_manifest() -> dict[str, Any]:
    """Return the ``.claude-plugin/marketplace.json`` content.

    Names the ``proteanhq`` marketplace with its owner and lists one plugin,
    ``protean``, sourced from the committed ``./plugins/protean`` tree. The shape
    matches the marketplace manifest Claude Code already reads for this owner, so
    the plugin installs without a schema change.
    """
    return {
        "name": MARKETPLACE_NAME,
        "owner": dict(_OWNER),
        "metadata": {"description": _MARKETPLACE_DESCRIPTION},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": PLUGIN_SOURCE,
                "description": _PLUGIN_DESCRIPTION,
            }
        ],
    }


def plugin_manifest(version: str) -> dict[str, Any]:
    """Return the ``plugins/protean/.claude-plugin/plugin.json`` content for *version*.

    Stamps the plugin with *version* (the framework version), so a consumer can
    tell which version's guidance the bundled skills carry, and declares the
    Apache-2.0 license and the Protean HQ author.
    """
    return {
        "name": PLUGIN_NAME,
        "description": _PLUGIN_DESCRIPTION,
        "version": version,
        "author": dict(_AUTHOR),
        "license": "Apache-2.0",
    }


def _dump_json(data: dict[str, Any]) -> bytes:
    """Serialize a manifest to the exact bytes the committed file carries.

    Two-space indent, a trailing newline, and UTF-8. The bytes are compared
    directly against the committed file, so the write and the compare agree on
    one representation and a generate-then-check round trip never reports false
    drift.
    """
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _iter_skill_files(root: Traversable) -> Iterator[tuple[str, bytes]]:
    """Yield ``(relative_posix_path, bytes)`` for every file under a skill.

    Walks the skill subtree in sorted order (so the render is deterministic),
    reads each file's exact bytes, and drops any ``__init__.py`` package marker.
    """
    for child in sorted(root.iterdir(), key=lambda entry: entry.name):
        if child.is_dir():
            for relative, data in _iter_skill_files(child):
                yield f"{child.name}/{relative}", data
        elif child.name != _PACKAGE_MARKER:
            yield child.name, child.read_bytes()


def render_plugin_files(version: str) -> dict[str, bytes]:
    """Render the whole plugin tree for *version* as a path-to-bytes mapping.

    Keys are repo-relative POSIX paths: the two manifests, then every skill file
    under ``plugins/protean/skills/``. The skills are projected in sorted order
    and copied byte for byte from the pack, so the result is deterministic and a
    committed tree written from it round-trips exactly.
    """
    files: dict[str, bytes] = {
        MARKETPLACE_PATH: _dump_json(marketplace_manifest()),
        PLUGIN_MANIFEST_PATH: _dump_json(plugin_manifest(version)),
    }
    skills_root = pack_files() / SKILLS_DIR
    for name in iter_skills():
        for relative, data in _iter_skill_files(skills_root / name):
            files[f"{PLUGIN_SKILLS_ROOT}/{name}/{relative}"] = data
    return files


def _committed_paths(root: Path) -> set[str]:
    """Return the repo-relative POSIX paths the committed plugin tree holds.

    The two roots this render owns are the marketplace manifest and the whole
    ``plugins/protean/`` tree. Reading both back lets the check flag a file on
    disk that the render no longer produces (a skill removed from the pack, say),
    not only a stale or missing one.
    """
    paths: set[str] = set()
    if (root / MARKETPLACE_PATH).is_file():
        paths.add(MARKETPLACE_PATH)
    plugin_root = root / PLUGIN_ROOT
    if plugin_root.is_dir():
        for path in plugin_root.rglob("*"):
            if path.is_file():
                paths.add(path.relative_to(root).as_posix())
    return paths


def plugin_drift(root: Path, version: str) -> list[str]:
    """Return the sorted drift between the committed tree under *root* and a render.

    One line per drifted path: ``missing`` when the render produces a file the
    tree lacks, ``stale`` when the bytes differ, and ``extra`` when the tree holds
    a file the render no longer produces. An empty list means the committed tree
    matches the render byte for byte. Reads only; writes nothing.
    """
    rendered = render_plugin_files(version)
    drift: list[str] = []
    for relative, data in rendered.items():
        target = root / relative
        if not target.is_file():
            drift.append(f"missing {relative}")
        elif target.read_bytes() != data:
            drift.append(f"stale {relative}")
    drift.extend(
        f"extra {relative}" for relative in _committed_paths(root) - set(rendered)
    )
    return sorted(drift)


def write_plugin(root: Path, version: str) -> None:
    """Write the rendered plugin tree under *root*, so it equals the render exactly.

    Writes every rendered file (creating parent directories) as raw bytes, so no
    newline translation can change what lands on disk. Then prunes any file the
    render no longer produces and removes the directories left empty, so a skill
    dropped from the pack does not leave an orphan behind.
    """
    rendered = render_plugin_files(version)
    for relative, data in rendered.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for relative in _committed_paths(root) - set(rendered):
        (root / relative).unlink()
    _prune_empty_dirs(root / PLUGIN_ROOT)


def _prune_empty_dirs(root: Path) -> None:
    """Remove empty directories under *root*, deepest first.

    Runs after the orphan sweep so a directory emptied by a removed skill does not
    linger. Does nothing when *root* is absent.
    """
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if not dirnames and not filenames:
            Path(dirpath).rmdir()
