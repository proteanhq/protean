"""Run the fenced Python blocks in Markdown files, one namespace per file.

``tests/dx/test_skill_snippets.py`` runs the DX-pack skills through this module,
and ``tests/docs/test_doc_pages_run.py`` runs the documentation pages.

A Python block is a fence opened with ``python`` or ``py``, optionally followed
by attributes such as ``hl_lines="2"`` or ``title="x.py"``, using backticks or
tildes. ``pycon``, ``ipython`` and every other language are not Python blocks.
A block indented under a list item, a tab (``=== "Tab"``) or an admonition has
its fence indent removed and is then dedented.

The blocks of one file run top to bottom in one namespace, because most blocks
build on an earlier block or name an element a later block defines
(``part_of="Order"``). The namespace starts with a prelude: ``domain =
Domain(...)``, the public names from ``protean``, the field types from
``protean.fields``, and ``__file__`` set to the Markdown file's path. After the
last block, every ``Domain`` built while the file ran that registered an
element is initialized with ``init(traverse=False)``, so a forward reference
must resolve by the end of the file. A reference that is still unresolved there
fails the file at the ``init`` step. A file that binds its own ``domain``
replaces the prelude's, and its domain is initialized the same way.

A block whose first line is ``# fragment`` is not run and does not touch the
namespace.

All files run in one child interpreter, each under its own module name and its
own ``Domain``, so registrations stay out of the test process. The child's
working directory is a temporary directory, so a block that writes files or
traverses the working directory touches nothing in the repository. Each file
has a timeout, enforced with ``SIGALRM`` where the platform has it.

:func:`include_expander` builds a source transform that replaces
``--8<-- "<spec>"`` lines with the code they include, the way
``pymdownx.snippets`` does when it builds the docs.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

FILE_TIMEOUT = 30.0

_FENCE_OPEN = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?:python|py)(?:[ \t]+[^`]*)?[ \t]*$"
)
_FRAGMENT = re.compile(r"^# fragment\b")


@dataclass(frozen=True)
class Block:
    line: int  # 1-based line number of the block's first code line
    source: str
    fragment: bool


class SnippetError(ValueError):
    """A block cannot be prepared to run, for example a broken include."""


def extract_blocks(text: str) -> list[Block]:
    """Return the fenced Python blocks in ``text``, in order.

    The fence's indentation is removed from every line of the block, and the
    block is then dedented, so a block nested under a list item, a tab or an
    admonition reads as top-level code.
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
        fence = match.group("fence")
        close = re.compile(
            r"^[ \t]*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$"
        )
        start = index + 1
        end = start
        while end < len(lines) and not close.match(lines[end]):
            end += 1
        body = [
            line[len(indent) :] if line.startswith(indent) else line.lstrip()
            for line in lines[start:end]
        ]
        blocks.append(make_block(start + 1, "\n".join(body) + "\n"))
        index = end + 1
    return blocks


def make_block(line: int, source: str) -> Block:
    """Dedent ``source`` and read its ``# fragment`` marker."""
    source = textwrap.dedent(source)
    first = source.split("\n", 1)[0].strip()
    return Block(line=line, source=source, fragment=bool(_FRAGMENT.match(first)))


# --- Includes ----------------------------------------------------------------

_INCLUDE = re.compile(r'^(?P<indent>[ \t]*)--8<--[ \t]+"(?P<spec>[^"]*)"[ \t]*$')
_SECTION_MARKER = re.compile(
    r"^.*?-+8<-+[ \t]+\[[ \t]*(?P<kind>start|end)[ \t]*:[ \t]*(?P<name>[\w-]+)[ \t]*\]"
)
_RANGE = re.compile(r"^(?P<file>[^:]+):(?P<start>[0-9]+):(?P<end>[0-9]+)$")
_SECTION = re.compile(r"^(?P<file>[^:]+):(?P<name>[\w-]+)$")


def _resolve(path: str, bases: Sequence[Path]) -> Path:
    for base in bases:
        candidate = base / path
        if candidate.is_file():
            return candidate
    names = ", ".join(base.name for base in bases)
    raise SnippetError(f"no file {path!r} under {names}")


def _without_markers(lines: list[str]) -> list[str]:
    return [line for line in lines if not _SECTION_MARKER.match(line)]


def read_include(spec: str, bases: Sequence[Path]) -> str:
    """Return the code ``--8<-- "<spec>"`` includes.

    ``file`` includes the whole file. ``file:start:end`` includes lines
    ``start`` to ``end``, counted from 1, both included; an ``end`` past the
    last line stops at the last line. ``file:name`` includes
    the lines between ``# --8<-- [start:name]`` and ``# --8<-- [end:name]``.
    Section marker lines are left out of every form. Any other form raises
    :class:`SnippetError`.
    """
    if ":" not in spec:
        path, form = spec, "file"
    elif match := _RANGE.match(spec):
        path, form = match.group("file"), "range"
    elif match := _SECTION.match(spec):
        path, form = match.group("file"), "section"
    else:
        raise SnippetError(f"unknown include form {spec!r}")
    if not path:
        raise SnippetError(f"unknown include form {spec!r}")
    lines = _resolve(path, bases).read_text(encoding="utf-8").splitlines()

    if form == "file":
        selected = lines
    elif form == "range":
        assert match is not None
        start, end = int(match.group("start")), int(match.group("end"))
        # The docs build stops a range at the end of the file, so an end
        # past it is accepted. A range with no lines in it is not.
        if start < 1 or end < start or start > len(lines):
            raise SnippetError(
                f"include {spec!r} asks for lines {start} to {end}, "
                f"but {path} has {len(lines)} lines"
            )
        selected = lines[start - 1 : end]
    else:
        assert match is not None
        name = match.group("name")
        bounds = [
            (index, marker.group("kind"))
            for index, line in enumerate(lines)
            if (marker := _SECTION_MARKER.match(line)) and marker.group("name") == name
        ]
        starts = [index for index, kind in bounds if kind == "start"]
        if not starts:
            raise SnippetError(f"include {spec!r}: no section {name!r} in {path}")
        ends = [index for index, kind in bounds if kind == "end" and index > starts[0]]
        if not ends:
            raise SnippetError(f"include {spec!r}: section {name!r} has no end marker")
        selected = lines[starts[0] + 1 : ends[0]]
    return "\n".join(_without_markers(selected))


def include_expander(bases: Sequence[Path]) -> Callable[[Block], Block]:
    """Return a transform that expands the ``--8<--`` lines in a block.

    Each included line keeps the include line's indentation, and the block is
    dedented again afterwards, as the docs build renders it. ``bases`` are the
    folders an include path is relative to, searched in order.
    """

    def expand(block: Block) -> Block:
        lines = []
        changed = False
        for line in block.source.splitlines():
            match = _INCLUDE.match(line)
            if match is None:
                lines.append(line)
                continue
            changed = True
            indent = match.group("indent")
            code = read_include(match.group("spec"), bases)
            lines.extend(indent + part if part else part for part in code.split("\n"))
        if not changed:
            return block
        expanded = make_block(block.line, "\n".join(lines) + "\n")
        # The marker is read from the page, never from included code.
        return replace(expanded, fragment=block.fragment)

    return expand


def load_blocks(
    path: Path, expand: Callable[[Block], Block] | None = None
) -> list[Block]:
    """Return the Python blocks of the file at ``path``, expanded by ``expand``.

    Raises :class:`SnippetError` naming the block's line when ``expand`` fails.
    """
    blocks = extract_blocks(path.read_text(encoding="utf-8"))
    if expand is None:
        return blocks
    expanded = []
    for block in blocks:
        try:
            expanded.append(expand(block))
        except SnippetError as exc:
            raise SnippetError(f"line {block.line}: {exc}") from None
    return expanded


def parse_problems(
    path: Path, label: str, expand: Callable[[Block], Block] | None = None
) -> list[str]:
    """List the blocks of ``path`` that cannot run for a reason in the page itself.

    A problem is an include that does not resolve, a ``python`` block that is a
    ``>>>`` REPL transcript, or a block that is not a fragment and does not
    parse. Each problem starts with ``label`` and the block's line.
    """
    try:
        blocks = load_blocks(path, expand)
    except SnippetError as exc:
        return [f"{label}: {exc}"]
    problems = []
    for block in blocks:
        first = next((line for line in block.source.splitlines() if line.strip()), "")
        if first.lstrip().startswith(">>>"):
            problems.append(
                f"{label}: line {block.line}: a '>>>' transcript; "
                "fence it as 'pycon', not 'python'"
            )
        elif not block.fragment:
            try:
                ast.parse(block.source)
            except SyntaxError as exc:
                problems.append(
                    f"{label}: line {block.line}: SyntaxError on line {exc.lineno} "
                    f"of the block: {exc.msg}"
                )
    return problems


# --- Running -----------------------------------------------------------------

# The child-interpreter runner. argv[1] is a JSON file holding the files and
# their blocks, the per-file timeout, and the report path. For each file it
# builds a fresh namespace, runs the non-fragment blocks in order, and then
# initializes every Domain built for the file that registered an element. It
# records the first failure (the block's starting line, or "init") and the
# starting lines of the blocks it did not run. A file the parent could not
# prepare carries an "error" and runs nothing. It writes the report to a file,
# so start-up logging and the blocks' own output cannot corrupt it.
_RUNNER = """
import builtins
import json
import signal
import sys
import types

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
# Hook ``__new__``, not ``__init__``: ``Domain.__init__`` names an unnamed
# domain after its caller's module, so its caller must stay the block.
built = []


def recording_new(cls, *args, **kwargs):
    instance = object.__new__(cls)
    built.append(instance)
    return instance


Domain.__new__ = recording_new


# Python 3.14 defers annotations (PEP 649); earlier versions evaluate them
# when the module, function or class is defined. Evaluate the ones a block
# defined right after it runs, so a block that names an undefined type fails
# on every version.
def evaluate_annotations(obj, module):
    if not isinstance(obj, (type, types.FunctionType)) or obj.__module__ != module:
        return
    annotate = getattr(obj, "__annotate__", None)
    if annotate is not None:
        annotate(1)
    if isinstance(obj, type):
        for member in vars(obj).values():
            member = getattr(member, "__func__", member)
            if isinstance(member, property):
                member = member.fget
            if isinstance(member, types.FunctionType):
                evaluate_annotations(member, module)

with open(sys.argv[1], encoding="utf-8") as handle:
    job = json.load(handle)
timeout = job["timeout"]
results = []
for index, item in enumerate(job["files"]):
    label = item["file"]
    blocks = [b for b in item["blocks"] if not b["fragment"]]
    if item.get("error"):
        results.append(
            {
                "file": label,
                "failure": item["error"],
                "not_run": [b["line"] for b in blocks],
            }
        )
        continue
    # Register the namespace as a real module: code that looks a class's
    # module up in ``sys.modules`` (dataclasses, typing) must find it.
    module = types.ModuleType("_dx_snippet_%d_" % index)
    sys.modules[module.__name__] = module
    namespace = module.__dict__
    namespace["__file__"] = item["path"]
    namespace["__builtins__"] = builtins
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
                before = {key: id(value) for key, value in namespace.items()}
                exec(compile(padded, label, "exec"), namespace)
                annotate = namespace.pop("__annotate__", None)
                if annotate is not None:
                    annotate(1)
                for key, value in list(namespace.items()):
                    if before.get(key) != id(value):
                        evaluate_annotations(value, namespace["__name__"])
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


def _job_entry(
    root: Path, path: Path, expand: Callable[[Block], Block] | None
) -> dict[str, object]:
    error = None
    try:
        blocks = load_blocks(path, expand)
    except SnippetError as exc:
        error = str(exc)
        blocks = extract_blocks(path.read_text(encoding="utf-8"))
    return {
        "file": path.relative_to(root).as_posix(),
        "path": str(path),
        "error": error,
        "blocks": [
            {"line": b.line, "source": b.source, "fragment": b.fragment} for b in blocks
        ],
    }


def run_snippets(
    root: Path,
    files: list[Path],
    tmp_path: Path,
    timeout: float = FILE_TIMEOUT,
    expand: Callable[[Block], Block] | None = None,
) -> list[dict]:
    """Run each file's blocks in a child interpreter and return its results.

    Each result is ``{"file", "failure", "not_run"}``, with ``file`` relative
    to ``root``. ``expand`` transforms each block before it runs; a
    :class:`SnippetError` it raises becomes the file's failure, and none of the
    file's blocks run.
    """
    work = tmp_path / "snippet-run"
    work.mkdir()
    job_path = work / "job.json"
    report_path = work / "report.json"
    job = {
        "timeout": timeout,
        "report": str(report_path),
        "files": [_job_entry(root, path, expand) for path in files],
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


def describe(result: dict) -> str:
    """Return the problem line for a failed result: file, failure, blocks not run."""
    message = f"{result['file']}: {result['failure']}"
    if result["not_run"]:
        lines = ", ".join(str(line) for line in result["not_run"])
        message += f"; not run: blocks at lines {lines}"
    return message


def evaluate(results: list[dict], allowlist: frozenset[str]) -> list[str]:
    """Compare the results with the allowlist and list the problems."""
    problems = []
    seen = set()
    for result in results:
        label = result["file"]
        seen.add(label)
        problems.extend(evaluate_one(result, allowlist))
    problems.extend(
        f"{label}: is on the allowlist but has no python blocks to run; "
        "remove the entry"
        for label in sorted(allowlist - seen)
    )
    return problems


def evaluate_one(result: dict, allowlist: frozenset[str]) -> list[str]:
    """Compare one file's result with the allowlist and list its problems."""
    label = result["file"]
    if result["failure"] is None and label in allowlist:
        return [f"{label}: every block passes; remove {label!r} from the allowlist"]
    if result["failure"] is not None and label not in allowlist:
        return [describe(result)]
    return []
