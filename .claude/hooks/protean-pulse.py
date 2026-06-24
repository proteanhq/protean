#!/usr/bin/env python3
"""SessionStart pulse: surface repo drift that nothing else flags.

Local-only and fast by default; prints NOTHING when everything is clean (a pulse
that always fires becomes wallpaper). Network checks (gh) are gated behind
PROTEAN_PULSE_NETWORK=1. Always exits 0 — never blocks session start.

Checks:
  1. Version drift across the bump-my-version tracked files (local).
  2. Malformed changelog fragment filenames in changes/ (local).
  3. Docs not wired into the mkdocs nav (local).
  4. Skills with no row in .claude/skills/INDEX.md (local).
  5. Fragments for already-CLOSED issues still unassembled (network, opt-in).
  6. `protean` on PATH resolving outside the project .venv (local).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

KAC = ("added", "changed", "deprecated", "removed", "fixed", "security")


def project_dir() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def version_drift(root: Path):
    cfg = root / ".bumpversion.toml"
    if tomllib is None or not cfg.exists():
        return None
    bv = tomllib.loads(cfg.read_text()).get("tool", {}).get("bumpversion", {})
    cv = bv.get("current_version")
    if not cv:
        return None
    files = [
        f["filename"]
        for f in bv.get("files", [])
        if isinstance(f, dict) and f.get("filename")
    ]
    bad = []
    for rel in files:
        p = root / rel
        if not p.exists():
            bad.append(f"{rel} (missing)")
        elif cv not in p.read_text(errors="ignore"):
            bad.append(rel)
    if bad:
        return f"version {cv} not found in: {', '.join(bad)} — bump files disagree"
    return None


def malformed_fragments(root: Path):
    d = root / "changes"
    if not d.is_dir():
        return None
    pat = re.compile(r"^\d+\.(?:%s)\.md$" % "|".join(KAC))
    bad = sorted(
        p.name
        for p in d.glob("*.md")
        if p.name != "README.md" and not pat.match(p.name)
    )
    if bad:
        return f"malformed changelog fragment(s): {', '.join(bad)} (expected <issue>.<category>.md)"
    return None


def orphan_docs(root: Path):
    mk = root / "mkdocs.yml"
    docs = root / "docs"
    if not mk.exists() or not docs.is_dir():
        return None
    nav = mk.read_text(errors="ignore")
    orphans = []
    for p in docs.rglob("*.md"):
        rel = p.relative_to(docs).as_posix()
        if rel.startswith("adr/"):  # ADRs are indexed separately, not all in nav
            continue
        if rel not in nav:
            orphans.append(rel)
    if orphans:
        orphans.sort()
        n = len(orphans)
        sample = ", ".join(orphans[:3])
        more = "" if n <= 3 else f" (+{n - 3} more)"
        return f"{n} doc(s) not in mkdocs nav: {sample}{more}"
    return None


def uncatalogued_skills(root: Path):
    idx = root / ".claude/skills/INDEX.md"
    sk = root / ".claude/skills"
    if not idx.exists() or not sk.is_dir():
        return None
    text = idx.read_text(errors="ignore")
    missing = [
        d.name
        for d in sorted(sk.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists() and f"`/{d.name}`" not in text
    ]
    if missing:
        return f"skill(s) missing from INDEX.md: {', '.join(missing)}"
    return None


def closed_issue_fragments(root: Path):
    if os.environ.get("PROTEAN_PULSE_NETWORK") != "1":
        return None
    d = root / "changes"
    if not d.is_dir():
        return None
    pat = re.compile(r"^(\d+)\.")
    issues = sorted(
        {
            m.group(1)
            for p in d.glob("*.md")
            if p.name != "README.md"
            for m in [pat.match(p.name)]
            if m
        },
        key=int,
    )
    closed = []
    for num in issues[:15]:
        try:
            out = subprocess.run(
                [
                    "gh",
                    "issue",
                    "view",
                    num,
                    "-R",
                    "proteanhq/protean",
                    "--json",
                    "state",
                    "-q",
                    ".state",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception:
            continue
        if out.returncode == 0 and out.stdout.strip().upper() == "CLOSED":
            closed.append(num)
    if closed:
        return f"{len(closed)} fragment(s) for CLOSED issues still unassembled: #{', #'.join(closed)} (run /changelog)"
    return None


def interpreter_drift(root: Path):
    """Warn when a project .venv exists but `protean` on PATH points elsewhere.

    This is the silent footgun where `protean test` resolves to a stale pyenv
    shim (missing deps → phantom collection errors) instead of the project's
    .venv. `uv run protean ...` / `make test` always use the right interpreter.
    """
    venv = root / ".venv"
    if not venv.is_dir():
        return None
    resolved = shutil.which("protean")
    if not resolved:
        return None  # nothing on PATH to disagree with
    try:
        resolved_parent = Path(resolved).resolve().parent
        venv_bin = (venv / "bin").resolve()
    except Exception:
        return None
    if resolved_parent != venv_bin:
        return (
            f"`protean` on PATH is {resolved} (not the project .venv) — "
            "use `uv run protean ...` or `make test` to avoid a stale interpreter"
        )
    return None


def main() -> None:
    root = project_dir()
    checks = (
        version_drift,
        malformed_fragments,
        orphan_docs,
        uncatalogued_skills,
        closed_issue_fragments,
        interpreter_drift,
    )
    lines = []
    for fn in checks:
        try:
            result = fn(root)
        except Exception:
            result = None
        if result:
            lines.append(f"  • {result}")
    if lines:
        print("⏩ protean-pulse — drift to review:")
        print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
