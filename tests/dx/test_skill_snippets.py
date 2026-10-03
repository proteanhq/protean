"""Run the fenced ``python`` blocks in every DX-pack skill's Markdown.

``tests/dx/test_examples.py`` runs the ``assets/*.py`` files. This test runs
the code blocks inside ``skills/*/SKILL.md`` and ``skills/*/references/*.md``.

The blocks of one file run top to bottom in one namespace, because most blocks
build on an earlier block or name an element a later block defines
(``part_of="Order"``). The namespace starts with a prelude: ``domain =
Domain(...)``, the public names from ``protean``, the field types from
``protean.fields``, and ``__file__`` set to the Markdown file's path. After the
last block, every ``Domain`` built while the file ran that registered an
element is initialized with ``init(traverse=False)``, so a forward reference must resolve
by the end of the file. A reference that is still unresolved there fails the
file at the ``init`` step.

A block whose first line is ``# fragment`` is not run and does not touch the
namespace. The marker is for a block that is not meant to run: a signature, a
partial method, a wrong example shown on purpose. A block meant to run that
fails stays unmarked, and its file goes on ``ALLOWLIST``. A file whose blocks
are all fragments runs nothing and passes.

The allowlist is keyed by file and is strict. A listed file may fail. A listed
file whose blocks all pass fails the test until its entry is removed.

All files run in one child interpreter, each under its own module name and its
own ``Domain``, so registrations stay out of this test process. The child's
working directory is a temporary directory, so a block that writes files or
traverses the working directory touches nothing in the repository. Each file
has a 30-second timeout, enforced with ``SIGALRM`` where the platform has it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the snippet runner reads skills by path",
        allow_module_level=True,
    )

FILE_TIMEOUT = 30.0

_FENCE_OPEN = re.compile(r"^(?P<indent>[ \t]*)```python[ \t]*$")
_FENCE_CLOSE = re.compile(r"^[ \t]*```[ \t]*$")
_FRAGMENT = re.compile(r"^# fragment\b")
_ANY_PY_FENCE = re.compile(r"^(```|~~~)\s*py", re.IGNORECASE)


@dataclass(frozen=True)
class Block:
    line: int  # 1-based line number of the block's first code line
    source: str
    fragment: bool


def extract_blocks(text: str) -> list[Block]:
    """Return the fenced ``python`` blocks in ``text``, in order.

    A fence indented inside a list item has its indentation removed from every
    line of the block.
    """
    blocks = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = _FENCE_OPEN.match(lines[index])
        if not match:
            index += 1
            continue
        indent = match.group("indent")
        start = index + 1
        end = start
        while end < len(lines) and not _FENCE_CLOSE.match(lines[end]):
            end += 1
        body = [
            line[len(indent) :] if line.startswith(indent) else line.lstrip()
            for line in lines[start:end]
        ]
        source = "\n".join(body) + "\n"
        first = body[0].strip() if body else ""
        blocks.append(
            Block(line=start + 1, source=source, fragment=bool(_FRAGMENT.match(first)))
        )
        index = end + 1
    return blocks


def discover_files(skills_root: Path) -> list[Path]:
    """Every ``SKILL.md`` and ``references/*.md`` holding a ``python`` block."""
    candidates = list(skills_root.glob("*/SKILL.md")) + list(
        skills_root.glob("*/references/*.md")
    )
    return sorted(
        path for path in candidates if extract_blocks(path.read_text(encoding="utf-8"))
    )


# The child-interpreter runner. argv[1] is a JSON file holding the files and
# their blocks, the per-file timeout, and the report path. For each file it
# builds a fresh namespace, runs the non-fragment blocks in order, and then
# initializes every Domain built for the file that registered an element. It records the first
# failure (the block's starting line, or "init") and the starting lines of the
# blocks it did not run. It writes the report to a file, so start-up logging
# and the blocks' own output cannot corrupt it.
_RUNNER = """
import builtins
import json
import signal
import sys

import protean
import protean.fields
from protean.domain import Domain


class SnippetTimeout(BaseException):
    pass


def on_alarm(signum, frame):
    raise SnippetTimeout()


has_alarm = hasattr(signal, "setitimer")

# Record every Domain built while a file runs, so the init step reaches a
# Domain that a later block rebinds, deletes or stores out of the namespace.
built = []
original_init = Domain.__init__


def recording_init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    built.append(self)


Domain.__init__ = recording_init

with open(sys.argv[1], encoding="utf-8") as handle:
    job = json.load(handle)
timeout = job["timeout"]
results = []
for index, item in enumerate(job["files"]):
    label = item["file"]
    blocks = [b for b in item["blocks"] if not b["fragment"]]
    namespace = {
        "__name__": "_dx_snippet_%d_" % index,
        "__file__": item["path"],
        "__builtins__": builtins,
    }
    for name in protean.__all__:
        namespace[name] = getattr(protean, name)
    for name in protean.fields.__all__:
        namespace[name] = getattr(protean.fields, name)
    built.clear()
    namespace["domain"] = Domain(name="Snippet%d" % index)
    failure = None
    not_run = []
    step = None
    if has_alarm:
        # A block may replace the handler; put it back for every file.
        signal.signal(signal.SIGALRM, on_alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        try:
            for position, block in enumerate(blocks):
                step = "line %d" % block["line"]
                not_run = [b["line"] for b in blocks[position + 1 :]]
                padded = "\\n" * (block["line"] - 1) + block["source"]
                exec(compile(padded, label, "exec"), namespace)
            not_run = []
            step = "init"
            for candidate in list(built):
                if candidate.registry.elements:
                    candidate.init(traverse=False)
        finally:
            if has_alarm:
                signal.setitimer(signal.ITIMER_REAL, 0)
    except SnippetTimeout:
        failure = "%s: timed out after %s seconds" % (step, timeout)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        failure = "%s: %s: %s" % (step, type(exc).__name__, exc)
    if failure is None:
        not_run = []
    results.append({"file": label, "failure": failure, "not_run": not_run})

with open(job["report"], "w", encoding="utf-8") as handle:
    json.dump(results, handle)
"""


def run_snippets(
    skills_root: Path,
    files: list[Path],
    tmp_path: Path,
    timeout: float = FILE_TIMEOUT,
) -> list[dict]:
    """Run each file's blocks in a child interpreter and return its results.

    Each result is ``{"file", "failure", "not_run"}``, with ``file`` relative
    to ``skills_root``.
    """
    work = tmp_path / "snippet-run"
    work.mkdir()
    job_path = work / "job.json"
    report_path = work / "report.json"
    job = {
        "timeout": timeout,
        "report": str(report_path),
        "files": [
            {
                "file": path.relative_to(skills_root).as_posix(),
                "path": str(path),
                "blocks": [
                    {"line": b.line, "source": b.source, "fragment": b.fragment}
                    for b in extract_blocks(path.read_text(encoding="utf-8"))
                ],
            }
            for path in files
        ],
    }
    job_path.write_text(json.dumps(job), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER, str(job_path)],
        capture_output=True,
        text=True,
        cwd=work,
        stdin=subprocess.DEVNULL,
        check=False,
        timeout=max(600.0, timeout * len(files) + 60),
    )
    assert report_path.is_file(), (
        f"the snippet runner crashed before writing its report "
        f"(exit {result.returncode}):\n{result.stderr[-4000:]}"
    )
    return json.loads(report_path.read_text(encoding="utf-8"))


def evaluate(results: list[dict], allowlist: frozenset[str]) -> list[str]:
    """Compare the results with the allowlist and list the problems."""
    problems = []
    seen = set()
    for result in results:
        label = result["file"]
        seen.add(label)
        failure = result["failure"]
        if failure is None and label in allowlist:
            problems.append(
                f"{label}: every block passes; remove {label!r} from the allowlist"
            )
        elif failure is not None and label not in allowlist:
            message = f"{label}: {failure}"
            if result["not_run"]:
                lines = ", ".join(str(line) for line in result["not_run"])
                message += f"; not run: blocks at lines {lines}"
            problems.append(message)
    problems.extend(
        f"{label}: is on the allowlist but has no python blocks to run; "
        "remove the entry"
        for label in sorted(allowlist - seen)
    )
    return problems


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
        "add-field/SKILL.md",
        "add-field/references/associations.md",
        "add-field/references/common-mistakes.md",
        "add-field/references/field-types.md",
        "add-field/references/validation.md",
        "add-read-model/SKILL.md",
        "add-read-model/references/choosing-storage.md",
        "add-read-model/references/cross-aggregate-read-model.md",
        "add-read-model/references/single-aggregate-read-model.md",
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
        "aggregate/SKILL.md",
        "aggregate/references/anti-patterns.md",
        "aggregate/references/configuration.md",
        "aggregate/references/invariants.md",
        "aggregate/references/with-entities.md",
        "aggregate/references/with-value-objects.md",
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
        "entity/SKILL.md",
        "entity/references/anti-patterns.md",
        "entity/references/configuration.md",
        "entity/references/nested-entities.md",
        "entity/references/with-hasmany.md",
        "entity/references/with-hasone.md",
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
        "process-manager/SKILL.md",
        "process-manager/references/anti-patterns.md",
        "process-manager/references/command-issuance.md",
        "process-manager/references/correlation.md",
        "process-manager/references/lifecycle.md",
        "projection/SKILL.md",
        "projection/references/anti-patterns.md",
        "projection/references/basic-projection.md",
        "projection/references/configuration-options.md",
        "projection/references/field-type-restrictions.md",
        "projection/references/persistence-querying.md",
        "projector/SKILL.md",
        "projector/references/anti-patterns.md",
        "projector/references/cross-aggregate.md",
        "projector/references/error-handling.md",
        "projector/references/multiple-projectors.md",
        "query-handler/SKILL.md",
        "query-handler/references/anti-patterns.md",
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
        "subscriber/SKILL.md",
        "subscriber/references/anti-corruption-layer.md",
        "subscriber/references/anti-patterns.md",
        "subscriber/references/basic-subscriber.md",
        "upcaster/SKILL.md",
        "upcaster/references/anti-patterns.md",
        "upcaster/references/upcaster-chain.md",
        "upcaster/references/when-to-upcast.md",
        "value-object/SKILL.md",
        "value-object/references/anti-patterns.md",
        "value-object/references/equality-and-immutability.md",
        "value-object/references/in-aggregates.md",
        "value-object/references/in-entities.md",
        "value-object/references/nested-value-objects.md",
        "value-object/references/with-invariants.md",
        "value-object/references/with-methods.md",
        "value-object/references/with-validation.md",
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
    other = root / "later" / "SKILL.md"
    other.parent.mkdir()
    other.write_text("```python\nraise ValueError('later ran')\n```\n")
    results = _run(root, tmp_path, timeout=0.5)
    assert results == [
        {
            "file": "later/SKILL.md",
            "failure": "line 2: ValueError: later ran",
            "not_run": [],
        },
        {
            "file": "skill/SKILL.md",
            "failure": "line 4: timed out after 0.5 seconds",
            "not_run": [9],
        },
    ]


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
