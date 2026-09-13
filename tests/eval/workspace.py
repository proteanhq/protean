"""The sandbox directory an eval run writes a project into.

A :class:`Workspace` is a directory plus the set of files the agent has written
into it through the ``write_file`` tool. It is the boundary that keeps a run's
file operations inside one directory: every path is resolved relative to the
root and rejected if it escapes.

The project hash covers the files the agent wrote through ``write_file``.
``run_verify`` runs ``protean verify``, whose init stage imports the domain and
whose tests stage runs pytest; both drop ``__pycache__`` and other byproducts
into the tree. Hashing only the written set keeps the produced project a pure
function of the agent's ``write_file`` calls, so a replay of the same turns
always hashes the same.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Workspace", "WorkspaceError"]


class WorkspaceError(Exception):
    """A file operation that is not allowed: an absolute path, a path that
    escapes the workspace root, or a path that resolves to the root itself."""


@dataclass
class Workspace:
    """A sandbox directory plus the set of files written into it.

    *root* must be an existing directory. It is resolved once at construction so
    later path checks compare against a stable, symlink-free base.
    """

    root: Path
    _root: Path = field(init=False, repr=False)
    _written: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self._root = Path(self.root).resolve()
        if not self._root.is_dir():
            raise WorkspaceError(f"workspace root is not a directory: {self.root}")

    def _resolve(self, rel: str, *, allow_root: bool = False) -> Path:
        """Resolve a workspace-relative path, rejecting anything that escapes.

        *allow_root* permits the workspace root itself (for ``list_dir(".")``);
        a file operation never allows it.

        A non-string path is rejected as a :class:`WorkspaceError` (not an
        ``AttributeError``), so a schema-invalid tool input becomes agent
        feedback rather than crashing the run.
        """
        if not isinstance(rel, str):
            raise WorkspaceError(f"path must be a string, got {type(rel).__name__}")
        # A NUL byte reaches the filesystem as a ValueError, which the tool layer
        # does not treat as feedback; reject it here as a WorkspaceError.
        if "\x00" in rel:
            raise WorkspaceError(f"path contains a NUL byte: {rel!r}")
        candidate = Path(rel.strip())
        if candidate.is_absolute():
            raise WorkspaceError(f"path must be relative to the workspace: {rel!r}")
        target = (self._root / candidate).resolve()
        if target == self._root:
            if allow_root:
                return target
            raise WorkspaceError(f"path resolves to the workspace root: {rel!r}")
        if self._root not in target.parents:
            raise WorkspaceError(f"path escapes the workspace: {rel!r}")
        return target

    def _relpath(self, target: Path) -> str:
        return target.relative_to(self._root).as_posix()

    def write(self, rel: str, content: str) -> str:
        """Write *content* to *rel* (creating parent directories) and track it.

        Returns the tracked, workspace-relative POSIX path. A non-string
        *content* is rejected as a :class:`WorkspaceError`, so a schema-invalid
        tool input becomes agent feedback rather than crashing the run.
        """
        if not isinstance(content, str):
            raise WorkspaceError(
                f"content must be a string, got {type(content).__name__}"
            )
        target = self._resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        # newline="" writes the bytes as given, without platform newline
        # translation, so a transcript recorded on one OS hashes the same on
        # replay on another.
        target.write_text(content, encoding="utf-8", newline="")
        relpath = self._relpath(target)
        self._written.add(relpath)
        return relpath

    def read(self, rel: str) -> str:
        """Return the text of *rel*. Raises :class:`WorkspaceError` if the file
        is missing or is not UTF-8 text (a binary byproduct such as a ``.pyc``),
        so a bad ``read_file`` becomes agent feedback rather than crashing the
        run (``UnicodeDecodeError`` is a ``ValueError``, not an ``OSError``)."""
        target = self._resolve(rel)
        if not target.is_file():
            raise WorkspaceError(f"no such file in the workspace: {rel!r}")
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(f"file is not UTF-8 text: {rel!r}") from exc

    def list_dir(self, rel: str = ".") -> list[str]:
        """Return the sorted entries of directory *rel* (default the root).

        Directory entries carry a trailing ``/`` so a caller can tell them from
        files without a second stat.
        """
        target = self._resolve(rel, allow_root=True)
        if not target.is_dir():
            raise WorkspaceError(f"not a directory in the workspace: {rel!r}")
        entries = [
            f"{child.name}/" if child.is_dir() else child.name
            for child in target.iterdir()
        ]
        return sorted(entries)

    def project_hash(self) -> str:
        """Return a stable hash of the files written into the workspace.

        Each written file contributes two lines, its path then the hex
        ``sha256`` of its bytes. The per-file blocks are sorted by path, joined
        with newlines, and that whole blob is hashed once. A file written and
        then deleted out of band is skipped. The result is prefixed ``sha256:``
        so the algorithm is legible in the stored transcript.
        """
        lines: list[str] = []
        for relpath in sorted(self._written):
            path = self._root / relpath
            # write() never creates a symlink, so a tracked path that is one was
            # swapped out of band (a generated test could point it at a host
            # file). Skip it rather than hash data from outside the workspace.
            if path.is_symlink() or not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{relpath}\n{digest}")
        blob = "\n".join(lines).encode("utf-8")
        return "sha256:" + hashlib.sha256(blob).hexdigest()
