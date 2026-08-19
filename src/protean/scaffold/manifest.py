"""Derived project manifest — ``.protean/project.json``.

The manifest is a small, derived record of a generated project's shape: the
package that holds the composition root, the domain's name, and the ADR-0030
layout invariants. Its contract is **derived, verifiable, never authoritative**.
Every field is recomputed from its own source on disk, and the stored file is
never consulted to override the code. A drift check recomputes the manifest and
reports where the stored file disagrees, changing nothing. A hand-edited
manifest that disagrees with the code therefore reads as drift and is not
honoured.

Usage::

    from pathlib import Path
    from protean.scaffold.manifest import check_manifest_drift, ManifestDriftStatus

    result = check_manifest_drift(Path("my_project"))
    if result.status == ManifestDriftStatus.DRIFTED:
        for div in result.divergences:
            print(f"{div.field}: stored {div.stored!r} != disk {div.recomputed!r}")
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "MANIFEST_VERSION",
    "ManifestDriftResult",
    "ManifestDriftStatus",
    "ManifestFieldDivergence",
    "ProjectLayout",
    "ProjectManifest",
    "check_manifest_drift",
    "load_stored_manifest",
    "reconcile_manifest",
    "write_manifest",
]

MANIFEST_VERSION = "1.0"
"""Schema version of the persisted manifest. Bumped when the JSON shape changes."""

_MANIFEST_FILENAME = "project.json"
_DEFAULT_PROTEAN_DIR = ".protean"
_DOMAIN_FILENAME = "domain.py"
_CONFIG_FILENAME = "domain.toml"


@dataclass(frozen=True)
class ProjectLayout:
    """The ADR-0030 layout invariants, as project-root-relative POSIX paths.

    Each path is stored relative to the project root and POSIX-normalised so the
    persisted JSON is stable across operating systems.
    """

    composition_root: str
    """``src/<package>/domain.py`` — the module that constructs the ``Domain``."""

    config_file: str
    """``src/<package>/domain.toml`` — domain config, beside the composition root."""

    tests_dir: str
    """``tests`` — the test tree, a sibling of ``src/``."""

    def to_dict(self) -> dict[str, str]:
        """Return the layout as a plain, JSON-serialisable dict."""
        return {
            "composition_root": self.composition_root,
            "config_file": self.config_file,
            "tests_dir": self.tests_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectLayout:
        """Rebuild a :class:`ProjectLayout` from its :meth:`to_dict` form."""
        return cls(
            composition_root=str(data["composition_root"]),
            config_file=str(data["config_file"]),
            tests_dir=str(data["tests_dir"]),
        )


@dataclass(frozen=True)
class ProjectManifest:
    """The derived record persisted to ``.protean/project.json``.

    ``domain_name`` is ``None`` when it cannot be derived from a string literal
    in the composition root (for example a computed or aliased name).
    """

    manifest_version: str
    package_name: str
    domain_name: str | None
    layout: ProjectLayout

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest as a plain, JSON-serialisable dict."""
        return {
            "manifest_version": self.manifest_version,
            "package_name": self.package_name,
            "domain_name": self.domain_name,
            "layout": self.layout.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectManifest:
        """Rebuild a :class:`ProjectManifest` from its :meth:`to_dict` form."""
        raw_domain = data["domain_name"]
        return cls(
            manifest_version=str(data["manifest_version"]),
            package_name=str(data["package_name"]),
            domain_name=None if raw_domain is None else str(raw_domain),
            layout=ProjectLayout.from_dict(data["layout"]),
        )


class ManifestDriftStatus(StrEnum):
    """Outcome of a manifest drift check."""

    MATCH = "match"
    """The stored manifest matches what is recomputed from disk."""

    DRIFTED = "drifted"
    """The stored manifest disagrees with disk on one or more fields."""

    NO_MANIFEST = "no_manifest"
    """No ``project.json`` was found in the given directory."""


@dataclass(frozen=True)
class ManifestFieldDivergence:
    """One field where the stored manifest disagrees with disk."""

    field: str
    """Dotted field name, e.g. ``package_name`` or ``layout.composition_root``."""

    stored: str | None
    """The value read from the stored manifest."""

    recomputed: str | None
    """The value recomputed from disk. This is what is authoritative."""


@dataclass(frozen=True)
class ManifestDriftResult:
    """Result returned by :func:`check_manifest_drift`. Mutates nothing."""

    status: ManifestDriftStatus
    """Overall outcome of the drift check."""

    divergences: tuple[ManifestFieldDivergence, ...]
    """Per-field divergences; empty unless ``status`` is ``DRIFTED``."""

    manifest_file: Path | None
    """Absolute path to the stored manifest, or ``None`` when absent."""


def _resolve_package_name(project_root: Path) -> str:
    """Return the single ``src/*/`` package that holds ``domain.py``.

    ADR-0030 fixes exactly one composition root per project, so exactly one
    ``src/<package>/domain.py`` is expected. Raise :exc:`ValueError` on zero or
    more than one, since the manifest cannot name an ambiguous root.
    """
    src_dir = project_root / "src"
    candidates = sorted(
        path.parent.name
        for path in src_dir.glob(f"*/{_DOMAIN_FILENAME}")
        if path.is_file()
    )
    if not candidates:
        raise ValueError(
            f"No composition root found: expected exactly one "
            f"src/*/{_DOMAIN_FILENAME} under {project_root}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Ambiguous composition root: found src/*/{_DOMAIN_FILENAME} in "
            f"multiple packages {candidates} under {project_root}; ADR-0030 "
            "fixes exactly one composition root per project"
        )
    return candidates[0]


def _derive_domain_name(domain_file: Path) -> str | None:
    """Parse the ``name=`` of the module-level ``Domain(...)`` call in *domain_file*.

    Only module-level assignments are considered, because ADR-0030 puts the
    composition root at module level: ``<domain> = Domain(name="...")``. A
    ``Domain(...)`` call nested inside a function or class body is not the
    composition root, so it is never read as the domain name.

    Returns the string-literal ``name`` of the first such assignment that
    carries one. Returns ``None`` when the file has no module-level
    ``Domain(...)`` assignment, when the ``name`` is not a string literal
    (computed or aliased), or when the file cannot be parsed. It never raises,
    so an unusual composition root degrades to "underivable" rather than
    crashing the reconcile.
    """
    try:
        source = domain_file.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        node = statement.value
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            called = func.id
        elif isinstance(func, ast.Attribute):
            called = func.attr
        else:
            continue
        if called != "Domain":
            continue
        for keyword in node.keywords:
            if keyword.arg != "name":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def reconcile_manifest(project_root: Path | str) -> ProjectManifest:
    """Recompute the manifest from *project_root* on disk.

    Each field is derived from its own source: ``package_name`` from the single
    ``src/*/`` package holding ``domain.py``, ``domain_name`` from the
    ``Domain(name=...)`` literal in that ``domain.py``, and ``layout`` from the
    ADR-0030 invariants relative to the resolved package.

    Raises :exc:`ValueError` when zero or more than one composition root exists.
    """
    root = Path(project_root)
    package_name = _resolve_package_name(root)
    package_dir = Path("src") / package_name
    domain_file = root / package_dir / _DOMAIN_FILENAME
    layout = ProjectLayout(
        composition_root=(package_dir / _DOMAIN_FILENAME).as_posix(),
        config_file=(package_dir / _CONFIG_FILENAME).as_posix(),
        tests_dir=Path("tests").as_posix(),
    )
    return ProjectManifest(
        manifest_version=MANIFEST_VERSION,
        package_name=package_name,
        domain_name=_derive_domain_name(domain_file),
        layout=layout,
    )


def write_manifest(project_root: Path | str) -> Path:
    """Reconcile from disk and write ``.protean/project.json``.

    Creates ``.protean/`` if it does not exist — the manifest writer is the
    first thing to create it — and writes the manifest with sorted keys and a
    trailing newline. Does not touch a pre-existing ``config.toml`` or
    ``ir.json`` sibling. Returns the absolute path of the written file.
    """
    root = Path(project_root)
    manifest = reconcile_manifest(root)
    protean_dir = root / _DEFAULT_PROTEAN_DIR
    protean_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = protean_dir / _MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path.resolve()


def load_stored_manifest(
    protean_dir: Path | str,
) -> tuple[ProjectManifest, Path] | None:
    """Load the stored manifest from *protean_dir*/project.json.

    Returns ``(manifest, path)`` if found and valid, or ``None`` if the file
    does not exist. Raises :exc:`ValueError` if the file exists but cannot be
    read, is not valid JSON, or does not carry the manifest shape.
    """
    manifest_path = Path(protean_dir) / _MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        content = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read {manifest_path}: {exc}") from exc
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {manifest_path}: {exc}") from exc
    try:
        return ProjectManifest.from_dict(data), manifest_path
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Malformed manifest in {manifest_path}: {exc}") from exc


def check_manifest_drift(
    project_root: Path | str,
    protean_dir: str = _DEFAULT_PROTEAN_DIR,
) -> ManifestDriftResult:
    """Compare the stored manifest against what is recomputed from disk.

    Loads ``<project_root>/<protean_dir>/project.json``, recomputes the manifest
    from disk, and compares field by field, ``manifest_version`` included, so a
    manifest written under an older schema reads as drift. Disk is always
    authoritative: the stored file is never trusted to override the code, so a
    hand-edited manifest that disagrees with disk is reported as drift. Mutates
    nothing.

    Returns a :class:`ManifestDriftResult` with status ``NO_MANIFEST`` when no
    stored file exists, ``MATCH`` when every field agrees, or ``DRIFTED`` with a
    per-field list of divergences otherwise.
    """
    root = Path(project_root)
    stored = load_stored_manifest(root / protean_dir)
    if stored is None:
        return ManifestDriftResult(
            status=ManifestDriftStatus.NO_MANIFEST,
            divergences=(),
            manifest_file=None,
        )

    stored_manifest, manifest_path = stored
    recomputed = reconcile_manifest(root)

    fields: list[tuple[str, str | None, str | None]] = [
        (
            "manifest_version",
            stored_manifest.manifest_version,
            recomputed.manifest_version,
        ),
        ("package_name", stored_manifest.package_name, recomputed.package_name),
        ("domain_name", stored_manifest.domain_name, recomputed.domain_name),
        (
            "layout.composition_root",
            stored_manifest.layout.composition_root,
            recomputed.layout.composition_root,
        ),
        (
            "layout.config_file",
            stored_manifest.layout.config_file,
            recomputed.layout.config_file,
        ),
        (
            "layout.tests_dir",
            stored_manifest.layout.tests_dir,
            recomputed.layout.tests_dir,
        ),
    ]
    divergences = tuple(
        ManifestFieldDivergence(field=name, stored=stored_val, recomputed=disk_val)
        for name, stored_val, disk_val in fields
        if stored_val != disk_val
    )

    status = (
        ManifestDriftStatus.MATCH if not divergences else ManifestDriftStatus.DRIFTED
    )
    return ManifestDriftResult(
        status=status,
        divergences=divergences,
        manifest_file=manifest_path.resolve(),
    )
