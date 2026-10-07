"""Run the fenced ``python`` blocks in every DX-pack skill's Markdown.

``tests/dx/test_examples.py`` runs the ``assets/*.py`` files. This test runs
the code blocks inside ``skills/*/SKILL.md`` and ``skills/*/references/*.md``,
through the runner in ``tests/support/snippets.py``. That module describes how
the blocks of one file run: one namespace per file, a prelude with ``domain``
and the ``protean`` names, ``init(traverse=False)`` after the last block, and a
30-second timeout per file.

A block whose first line is ``# fragment`` is not run. The marker is for a
block that is not meant to run: a signature, part of a class or a method, a
wrong example shown on purpose, code that needs a service the core lane does
not run, or code that starts a server or otherwise blocks. A block meant to run that fails stays unmarked, and its file
goes on ``ALLOWLIST``. A file whose blocks are all fragments runs nothing and
passes.

The allowlist is keyed by file and is strict. A listed file may fail. A listed
file whose blocks all pass fails the test until its entry is removed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean import dx
from tests.support.snippets import (
    FILE_TIMEOUT,
    Block,
    evaluate,
    extract_blocks,
    run_snippets,
)

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the snippet runner reads skills by path",
        allow_module_level=True,
    )

_ANY_PY_FENCE = re.compile(r"^(```|~~~)\s*py", re.IGNORECASE)


def discover_files(skills_root: Path) -> list[Path]:
    """Every ``SKILL.md`` and ``references/*.md`` holding a ``python`` block."""
    candidates = list(skills_root.glob("*/SKILL.md")) + list(
        skills_root.glob("*/references/*.md")
    )
    return sorted(
        path for path in candidates if extract_blocks(path.read_text(encoding="utf-8"))
    )


# Files with a block that fails today, relative to the skills root. Fix the
# file, then delete its entry.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "add-command/SKILL.md",
        "add-command/references/create-aggregate-flow.md",
        "add-command/references/multiple-commands-flow.md",
        "add-command/references/update-aggregate-flow.md",
        "add-domain-service-flow/SKILL.md",
        "add-domain-service-flow/references/domain-service-patterns.md",
        "add-event/SKILL.md",
        "add-event/references/multiple-events-flow.md",
        "add-event/references/same-aggregate-flow.md",
        "add-saga-flow/SKILL.md",
        "add-saga-flow/references/compensation.md",
        "add-saga-flow/references/saga-lifecycle.md",
        "add-subscriber-flow/SKILL.md",
        "add-subscriber-flow/references/anti-corruption-layer.md",
        "add-subscriber-flow/references/external-integration.md",
        "add-use-case/SKILL.md",
        "add-use-case/references/command-flow-patterns.md",
        "add-validation/SKILL.md",
        "add-validation/references/layer3-aggregate-invariants.md",
        "add-validation/references/layer4-handler-guards.md",
        "api-endpoint/SKILL.md",
        "api-endpoint/references/anti-patterns.md",
        "api-endpoint/references/request-validation.md",
        "api-endpoint/references/response-patterns.md",
        "api-endpoint/references/testing-endpoints.md",
        "application-service/SKILL.md",
        "application-service/references/anti-patterns.md",
        "application-service/references/error-handling.md",
        "application-service/references/return-values.md",
        "application-service/references/unit-of-work.md",
        "application-service/references/use-case-decorator.md",
        "audit-domain/SKILL.md",
        "audit-domain/references/anti-patterns.md",
        "audit-domain/references/detection-heuristics.md",
        "command-handler/SKILL.md",
        "command-handler/references/anti-patterns.md",
        "command-handler/references/error-handling.md",
        "command-handler/references/loading-aggregates.md",
        "command-handler/references/return-values.md",
        "command-handler/references/unit-of-work.md",
        "command/SKILL.md",
        "command/references/anti-patterns.md",
        "command/references/command-inheritance.md",
        "command/references/command-processing.md",
        "command/references/command-validation.md",
        "command/references/with-value-objects.md",
        "custom-validator/SKILL.md",
        "custom-validator/references/basic-validators.md",
        "custom-validator/references/composing-validators.md",
        "domain-service/SKILL.md",
        "domain-service/references/callable-class.md",
        "domain-service/references/class-methods.md",
        "domain-service/references/instance-methods.md",
        "domain-service/references/invariants.md",
        "event-handler/SKILL.md",
        "event-handler/references/anti-patterns.md",
        "event-handler/references/any-handler.md",
        "event-handler/references/cross-aggregate-patterns.md",
        "event-handler/references/cross-aggregate.md",
        "event-handler/references/error-handling.md",
        "event-sourced-aggregate/SKILL.md",
        "event-sourced-aggregate/references/anti-patterns.md",
        "event-sourced-aggregate/references/apply-decorator.md",
        "event-sourced-aggregate/references/event-sourced-repository.md",
        "event/SKILL.md",
        "event/references/anti-patterns.md",
        "event/references/delta-events.md",
        "event/references/event-versioning.md",
        "event/references/fact-events.md",
        "event/references/raising-events.md",
        "event/references/with-value-objects.md",
        "extract-bounded-context/SKILL.md",
        "extract-bounded-context/references/event-integration.md",
        "generate-test-scaffold/SKILL.md",
        "generate-test-scaffold/references/handler-tests.md",
        "message-enrichment/SKILL.md",
        "query/SKILL.md",
        "query/references/anti-patterns.md",
        "refactor-extract-value-object/SKILL.md",
        "refactor-extract-value-object/references/migration-guide.md",
        "refactor-introduce-events/SKILL.md",
        "refactor-introduce-events/references/anti-patterns.md",
        "refactor-introduce-events/references/event-design-guide.md",
        "refactor-move-logic-to-aggregate/SKILL.md",
        "refactor-move-logic-to-aggregate/references/anti-patterns.md",
        "refactor-move-logic-to-aggregate/references/identifying-logic-leaks.md",
        "repository/SKILL.md",
        "repository/references/anti-patterns.md",
        "repository/references/custom-queries.md",
        "repository/references/database-specific.md",
        "repository/references/default-repository.md",
        "repository/references/unit-of-work.md",
        "split-aggregate/SKILL.md",
        "upcaster/SKILL.md",
        "upcaster/references/anti-patterns.md",
        "upcaster/references/upcaster-chain.md",
        "upcaster/references/when-to-upcast.md",
    }
)


def test_snippet_discovery_is_not_vacuous():
    files = discover_files(SKILLS_ROOT)
    blocks = sum(len(extract_blocks(p.read_text(encoding="utf-8"))) for p in files)
    independent = 0
    for path in SKILLS_ROOT.rglob("*.md"):
        relative = path.relative_to(SKILLS_ROOT).parts
        in_scope = relative[1:] == ("SKILL.md",) or (
            len(relative) == 3 and relative[1] == "references"
        )
        if in_scope:
            # Count every fence that opens with a ``py`` tag in any spelling,
            # so a variant the extractor skips breaks the count.
            independent += sum(
                1
                for line in path.read_text(encoding="utf-8").splitlines()
                if _ANY_PY_FENCE.match(line.strip())
            )
    assert files, "discovered no Markdown files with python blocks"
    assert blocks == independent
    assert len(files) >= 150
    assert blocks >= 1300


def test_every_skill_snippet_runs_or_is_allowlisted(tmp_path):
    files = discover_files(SKILLS_ROOT)
    results = run_snippets(SKILLS_ROOT, files, tmp_path)

    assert [r["file"] for r in results] == [
        p.relative_to(SKILLS_ROOT).as_posix() for p in files
    ]
    problems = evaluate(results, ALLOWLIST)
    assert problems == [], "skill snippet failures:\n" + "\n".join(problems)


# --- Negative tests on synthetic skill folders -------------------------------


def _skill(tmp_path: Path, *blocks: str, name: str = "SKILL.md") -> Path:
    """Write a skill file whose python blocks are ``blocks``; return the root.

    Each block sits after a one-line paragraph, so block ``n`` (from 0) starts
    on line ``4 + 4 * n`` when it is a single line.
    """
    root = tmp_path / "skills"
    target = root / "skill" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    parts = ["# Skill"] + [f"Text.\n```python\n{block}\n```" for block in blocks]
    target.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return root


def _run(root: Path, tmp_path: Path, timeout: float = FILE_TIMEOUT) -> list[dict]:
    return run_snippets(root, discover_files(root), tmp_path, timeout=timeout)


def test_extract_blocks_reads_lines_indentation_and_the_marker():
    text = (
        "Intro\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "- item\n"
        "  ```python\n"
        "  # fragment\n"
        "  def f(self):\n"
        "  ```\n"
        "```toml\n"
        "a = 1\n"
        "```\n"
        "```python\n"
        "y = 2  # fragment\n"
        "```\n"
    )
    assert extract_blocks(text) == [
        Block(line=3, source="x = 1\n", fragment=False),
        Block(line=7, source="# fragment\ndef f(self):\n", fragment=True),
        Block(line=14, source="y = 2  # fragment\n", fragment=False),
    ]


def test_a_file_without_python_blocks_is_not_discovered(tmp_path):
    root = tmp_path / "skills"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_text("# Skill\n\n```toml\na = 1\n```\n")
    assert discover_files(root) == []


def test_a_raising_block_names_the_file_line_and_blocks_not_run(tmp_path):
    root = _skill(tmp_path, "x = 1", "raise ValueError('boom')", "y = 2", "z = 3")
    results = _run(root, tmp_path)
    assert results == [
        {
            "file": "skill/SKILL.md",
            "failure": "line 8: ValueError: boom",
            "not_run": [12, 16],
        }
    ]
    assert evaluate(results, frozenset()) == [
        "skill/SKILL.md: line 8: ValueError: boom; not run: blocks at lines 12, 16"
    ]


def test_the_traceback_line_is_the_line_in_the_markdown_file(tmp_path):
    # The second block starts on line 8, so its `1 / 0` sits on line 10.
    root = _skill(
        tmp_path,
        "x = 1",
        "import traceback\ntry:\n    1 / 0\nexcept ZeroDivisionError as exc:\n"
        "    raise ValueError(traceback.extract_tb(exc.__traceback__)[-1].lineno)",
    )
    results = _run(root, tmp_path)
    assert results[0]["failure"] == "line 8: ValueError: 10"


def test_a_block_can_use_a_name_from_the_block_before(tmp_path):
    root = _skill(tmp_path, "total = 2", "assert total == 2")
    assert _run(root, tmp_path) == [
        {"file": "skill/SKILL.md", "failure": None, "not_run": []}
    ]


def test_the_prelude_provides_domain_protean_names_and_fields(tmp_path):
    root = _skill(
        tmp_path,
        "assert isinstance(domain, Domain)\n"
        "assert handle is not None and String is not None and __file__.endswith('SKILL.md')",
    )
    assert _run(root, tmp_path)[0]["failure"] is None


def test_a_forward_reference_resolved_by_a_later_block_passes(tmp_path):
    root = _skill(
        tmp_path,
        "@domain.event(part_of='Order')\nclass OrderPlaced:\n    order_id = Identifier()",
        "@domain.aggregate\nclass Order:\n    name = String()",
    )
    assert _run(root, tmp_path)[0]["failure"] is None


def test_an_unresolved_part_of_fails_at_the_init_step(tmp_path):
    root = _skill(
        tmp_path,
        "@domain.event(part_of='Order')\nclass OrderPlaced:\n    order_id = Identifier()",
    )
    results = _run(root, tmp_path)
    failure = results[0]["failure"]
    assert failure.startswith("init: ConfigurationError: ")
    assert "`OrderPlaced` references `Order` via part_of" in failure
    assert evaluate(results, frozenset()) == [f"skill/SKILL.md: {failure}"]


def test_a_domain_the_blocks_declare_is_initialized_too(tmp_path):
    root = _skill(
        tmp_path,
        "other = Domain(name='Other')\n"
        "@other.event(part_of='Missing')\nclass Happened:\n    x = String()",
    )
    assert _run(root, tmp_path)[0]["failure"].startswith("init: ConfigurationError")


def test_a_fragment_is_skipped_and_the_next_block_runs(tmp_path):
    root = _skill(
        tmp_path,
        "# fragment\nmarker = 1\nraise ValueError('never run')",
        "assert 'marker' not in globals()\nraise RuntimeError('next block ran')",
    )
    results = _run(root, tmp_path)
    # The second block runs (its error is reported) and saw no `marker`.
    assert results[0]["failure"] == "line 10: RuntimeError: next block ran"


def test_a_file_whose_only_failing_block_is_a_fragment_passes(tmp_path):
    root = _skill(tmp_path, "# fragment\ndef broken(self):", "x = 1")
    results = _run(root, tmp_path)
    assert results[0]["failure"] is None
    assert evaluate(results, frozenset()) == []


def test_an_allowlisted_file_that_passes_says_to_remove_the_entry(tmp_path):
    root = _skill(tmp_path, "x = 1")
    results = _run(root, tmp_path)
    assert evaluate(results, frozenset({"skill/SKILL.md"})) == [
        "skill/SKILL.md: every block passes; remove 'skill/SKILL.md' from the allowlist"
    ]


def test_an_allowlisted_failing_file_passes(tmp_path):
    root = _skill(tmp_path, "raise ValueError('known')")
    results = _run(root, tmp_path)
    assert evaluate(results, frozenset({"skill/SKILL.md"})) == []


def test_an_allowlist_entry_for_a_missing_file_fails(tmp_path):
    root = _skill(tmp_path, "x = 1")
    results = _run(root, tmp_path)
    assert evaluate(results, frozenset({"skill/references/gone.md"})) == [
        (
            "skill/references/gone.md: is on the allowlist but has no python blocks "
            "to run; remove the entry"
        )
    ]


def test_reference_files_are_run_too(tmp_path):
    root = _skill(tmp_path, "raise ValueError('ref')", name="references/guide.md")
    assert evaluate(_run(root, tmp_path), frozenset()) == [
        "skill/references/guide.md: line 4: ValueError: ref"
    ]


@pytest.mark.skipif(
    not hasattr(__import__("signal"), "setitimer"),
    reason="the per-file timeout needs SIGALRM",
)
def test_a_block_past_the_timeout_is_reported_and_the_next_file_runs(tmp_path):
    root = _skill(tmp_path, "import time\ntime.sleep(30)", "x = 1")
    # "tail" sorts after "skill", so its result shows the run went on.
    other = root / "tail" / "SKILL.md"
    other.parent.mkdir()
    other.write_text("```python\nraise ValueError('tail ran')\n```\n")
    results = _run(root, tmp_path, timeout=0.5)
    assert results == [
        {
            "file": "skill/SKILL.md",
            "failure": "line 4: timed out after 0.5 seconds",
            "not_run": [9],
        },
        {
            "file": "tail/SKILL.md",
            "failure": "line 2: ValueError: tail ran",
            "not_run": [],
        },
    ]


@pytest.mark.parametrize(
    "block",
    [
        "email: Undefined = 1",
        "def get(user_id) -> Undefined:\n    pass",
        "class Service:\n    def get(self, user_id: Undefined):\n        pass",
    ],
)
def test_an_annotation_naming_an_undefined_type_fails_on_every_version(tmp_path, block):
    root = _skill(tmp_path, block, "x = 1")
    assert _run(root, tmp_path) == [
        {
            "file": "skill/SKILL.md",
            "failure": "line 4: NameError: name 'Undefined' is not defined",
            "not_run": [8 + block.count("\n")],
        }
    ]


def test_an_unnamed_domain_is_named_after_the_snippet_module(tmp_path):
    root = _skill(
        tmp_path, "unnamed = Domain()\nassert unnamed.name == __name__, unnamed.name"
    )
    assert _run(root, tmp_path)[0]["failure"] is None


def test_a_dataclass_with_a_string_annotation_runs(tmp_path):
    root = _skill(
        tmp_path,
        "from dataclasses import dataclass\n\n@dataclass\nclass Point:\n"
        "    value: 'int' = 1\n\nassert Point().value == 1",
    )
    assert _run(root, tmp_path)[0]["failure"] is None


@pytest.mark.parametrize(
    "rebind",
    [
        "domain = Domain(name='Replacement')",
        "del domain",
        "holder = {'d': domain}\ndel domain",
    ],
)
def test_a_domain_the_namespace_no_longer_holds_is_initialized(tmp_path, rebind):
    root = _skill(
        tmp_path,
        "@domain.event(part_of='Order')\nclass OrderPlaced:\n    order_id = Identifier()",
        rebind,
    )
    assert _run(root, tmp_path)[0]["failure"].startswith("init: ConfigurationError")


def test_a_fragment_marker_below_the_first_line_does_not_skip_the_block(tmp_path):
    root = _skill(tmp_path, "x = 1\n# fragment\nraise ValueError('runs')")
    assert _run(root, tmp_path)[0]["failure"] == "line 4: ValueError: runs"


@pytest.mark.skipif(
    not hasattr(__import__("signal"), "setitimer"),
    reason="the per-file timeout needs SIGALRM",
)
def test_a_block_that_replaces_the_alarm_handler_does_not_disable_later_timeouts(
    tmp_path,
):
    root = tmp_path / "skills"
    first = root / "a" / "SKILL.md"
    first.parent.mkdir(parents=True)
    first.write_text(
        "```python\nimport signal\nsignal.signal(signal.SIGALRM, lambda *a: None)\n```\n"
    )
    second = root / "b" / "SKILL.md"
    second.parent.mkdir()
    second.write_text("```python\nimport time\ntime.sleep(30)\n```\n")
    results = _run(root, tmp_path, timeout=0.5)
    assert results[1] == {
        "file": "b/SKILL.md",
        "failure": "line 2: timed out after 0.5 seconds",
        "not_run": [],
    }
