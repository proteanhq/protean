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

A block that registers an upcaster under a name an earlier block used for a
different edge (event, from-version, to-version) fails at that block, because
the registry would drop the earlier upcaster before init checks the chains.

A block whose first line is ``# fragment`` is not run and does not touch the
namespace.

All files run in one child interpreter, each under its own module name and its
own ``Domain``, so registrations stay out of the test process. The child starts
in a temporary directory, so a relative path in a block resolves inside it.
Each file has a timeout, enforced with ``SIGALRM`` where the platform has it.
Closing what a file left open (a unit of work or a domain context) gets the
same timeout again, because a rollback or a teardown callback can hang. A file
still running at twice its timeout (a block that catches the timeout, or a
platform without ``SIGALRM``) stops the child; the file is reported as stuck
and a new child runs the files after it.

:func:`include_expander` builds a source transform that replaces
``--8<-- "<spec>"`` lines with the code they include, the way
``pymdownx.snippets`` does when it builds the docs. Any other ``--8<--`` line
in a block is an include form the expander does not know, and fails.
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
# Every line the docs build reads as an include, in any of its forms.
_ANY_INCLUDE = re.compile(r"^[ \t]*;?-+8<-+")
_SECTION_MARKER = re.compile(
    r"^.*?-+8<-+[ \t]+\[[ \t]*(?P<kind>start|end)[ \t]*:[ \t]*(?P<name>[\w-]+)[ \t]*\]"
)
_RANGE = re.compile(r"^(?P<file>[^:]+):(?P<start>[0-9]+):(?P<end>[0-9]+)$")
_SECTION = re.compile(r"^(?P<file>[^:]+):(?P<name>[\w-]+)$")


def _resolve(path: str, bases: Sequence[Path]) -> Path:
    for base in bases:
        candidate = (base / path).resolve()
        # The docs build refuses a path that leaves its base folder.
        if not candidate.is_relative_to(base.resolve()):
            continue
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

    Each included line gets the include line's indentation in front of its own,
    as the docs build renders it. The block is not dedented again, so a section
    whose code is indented in its file (a method) stays indented, and a block
    holding only that include does not parse. ``bases`` are the folders an
    include path is relative to, searched in order.

    A ``--8<--`` line in any other form raises :class:`SnippetError`.
    """

    def expand(block: Block) -> Block:
        lines = []
        changed = False
        for line in block.source.splitlines():
            match = _INCLUDE.match(line)
            if match is None:
                if _ANY_INCLUDE.match(line):
                    raise SnippetError(f"unknown include form {line.strip()!r}")
                lines.append(line)
                continue
            changed = True
            indent = match.group("indent")
            code = read_include(match.group("spec"), bases)
            lines.extend(indent + part if part else part for part in code.split("\n"))
        if not changed:
            return block
        # The marker is read from the page, never from included code.
        return replace(block, source="\n".join(lines) + "\n")

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

# A child exits with this code when a file runs past its hard limit.
_STUCK_EXIT = 86

# The child-interpreter runner. argv[1] is a JSON file holding the files and
# their blocks, the per-file timeout, the hard limit, and the report path. For
# each file it builds a fresh namespace, runs the non-fragment blocks in order,
# initializes every Domain built for the file that registered an element, and
# then closes any unit of work or domain context the file left open. It records
# the first failure (the block's starting line, "init" or "cleanup") and the
# starting lines of the blocks it did not run. A file the parent could
# not prepare carries an "error" and runs nothing.
#
# The report is a file of JSON lines, written and flushed as the child goes: a
# "step" line before each block, the init step and the cleanup step, and a
# "result" line after each file. If a file is still running at the hard limit,
# a watchdog thread ends the child, and the parent reads which step was running
# from the report. Writing to a file keeps start-up logging and the blocks' own
# output out of it.
_RUNNER = """
import builtins
import json
import os
import signal
import sys
import threading
import types

import protean
import protean.fields
from protean.domain import Domain
from protean.utils.globals import _domain_context_stack, _uow_context_stack


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


# The registry keys an element by its qualified name and silently replaces an
# earlier class registered under the same name. Most elements are checked when
# their class body runs, so a block may redefine ``Order`` to show it growing.
# An upcaster is checked only at init, when its chain is built from each
# upcaster's edge: the event it targets and the versions it maps between. A
# block that reuses an upcaster name for a different edge drops the earlier
# edge from that check, so the file fails at that block. Reusing a name for the
# same edge drops nothing init would check, and passes.
class DuplicateElement(Exception):
    pass


def edge(cls):
    meta = cls.meta_
    target = meta.event_type
    return (getattr(target, "__name__", target), meta.from_version, meta.to_version)


def registered():
    records = {}
    for candidate in built:
        upcasters = candidate.registry._elements.get("UPCASTER", {})
        for qualname, record in upcasters.items():
            records[(id(candidate), qualname)] = record.cls
    return records


def check_no_replacement(earlier):
    for key, cls in registered().items():
        if key in earlier and edge(earlier[key]) != edge(cls):
            raise DuplicateElement(
                "%s replaces an upcaster of the same name for %s v%s to v%s;"
                " give each upcaster its own class name"
                % ((key[1],) + edge(earlier[key]))
            )

with open(sys.argv[1], encoding="utf-8") as handle:
    job = json.load(handle)
timeout = job["timeout"]
report = open(job["report"], "a", encoding="utf-8")


def emit(record):
    report.write(json.dumps(record) + "\\n")
    report.flush()


# A file may push a domain context or open a unit of work and leave it open.
# Close both, so the next file cannot pass by using this file's domain.
# Rolling back and popping through the objects releases any session and runs
# the domain's teardown callbacks. Closing runs under its own timeout, because
# a rollback or a teardown callback is page code and can hang. Return the
# first problem, because the page left something it could not close. Whatever
# a timeout leaves on the stacks is dropped without running more page code.
#
# A rollback or teardown callback is page code, so its failure is read the way
# a block's is: anything it raises, ``SystemExit`` included, is the page's
# failure. Only the runner's own timeout and an interrupt pass through.
def close_one(close):
    try:
        close()
    except (SnippetTimeout, KeyboardInterrupt):
        raise
    except BaseException as exc:
        return "%s: %s" % (type(exc).__name__, exc)
    return None


def close_left_open():
    problem = None
    if has_alarm:
        signal.signal(signal.SIGALRM, on_alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        while (uow := _uow_context_stack.top) is not None:
            found = close_one(uow.rollback)
            problem = problem or found
            if _uow_context_stack.top is uow:
                _uow_context_stack.pop()
        while (context := _domain_context_stack.top) is not None:
            found = close_one(lambda: context.pop(None))
            problem = problem or found
            if _domain_context_stack.top is context:
                _domain_context_stack.pop()
    except SnippetTimeout:
        problem = problem or "timed out after %s seconds" % timeout
    finally:
        if has_alarm:
            signal.setitimer(signal.ITIMER_REAL, 0)
        while _uow_context_stack.top is not None:
            _uow_context_stack.pop()
        while _domain_context_stack.top is not None:
            _domain_context_stack.pop()
    return problem


for index, item in enumerate(job["files"], start=job["first_index"]):
    label = item["file"]
    blocks = [b for b in item["blocks"] if not b["fragment"]]
    if item.get("error"):
        emit(
            {
                "result": {
                    "file": label,
                    "failure": item["error"],
                    "not_run": [b["line"] for b in blocks],
                }
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
    watchdog = threading.Timer(job["hard_timeout"], os._exit, args=(job["stuck_exit"],))
    watchdog.daemon = True
    watchdog.start()
    if has_alarm:
        # A block may replace the handler; put it back for every file.
        signal.signal(signal.SIGALRM, on_alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        try:
            try:
                for position, block in enumerate(blocks):
                    step = "line %d" % block["line"]
                    not_run = [b["line"] for b in blocks[position + 1 :]]
                    emit({"step": step, "not_run": not_run})
                    padded = "\\n" * (block["line"] - 1) + block["source"]
                    before = {key: id(value) for key, value in namespace.items()}
                    earlier = registered()
                    # Domain() takes its root folder from the caller's file
                    # name; a relative name would resolve against the scratch
                    # folder.
                    exec(compile(padded, item["path"], "exec"), namespace)
                    check_no_replacement(earlier)
                    annotate = namespace.pop("__annotate__", None)
                    if annotate is not None:
                        annotate(1)
                    for key, value in list(namespace.items()):
                        if before.get(key) != id(value):
                            evaluate_annotations(value, namespace["__name__"])
                not_run = []
                step = "init"
                emit({"step": step, "not_run": not_run})
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
        # The watchdog stays armed, so a close that ignores the timeout still
        # stops at the hard limit, reported as the cleanup step.
        emit({"step": "cleanup", "not_run": not_run})
        problem = close_left_open()
        if failure is None and problem is not None:
            failure = "cleanup: " + problem
    finally:
        watchdog.cancel()
    emit({"result": {"file": label, "failure": failure, "not_run": not_run}})
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


def _read_report(path: Path) -> tuple[list[dict], dict | None]:
    """Return the finished results in a report, and the last step after them."""
    results: list[dict] = []
    step = None
    if not path.is_file():
        return results, step
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if "result" in record:
            results.append(record["result"])
            step = None
        else:
            step = record
    return results, step


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

    A file still running at twice ``timeout``, or one that crashes the child,
    fails with the step that was running, and a new child runs the files after
    it.
    """
    work = tmp_path / "snippet-run"
    work.mkdir()
    entries = [_job_entry(root, path, expand) for path in files]
    hard_timeout = timeout * 2
    results: list[dict] = []
    attempt = 0
    while len(results) < len(entries):
        attempt += 1
        pending = entries[len(results) :]
        job_path = work / f"job-{attempt}.json"
        report_path = work / f"report-{attempt}.jsonl"
        job = {
            "timeout": timeout,
            "hard_timeout": hard_timeout,
            "stuck_exit": _STUCK_EXIT,
            "report": str(report_path),
            "first_index": len(results),
            "files": pending,
        }
        job_path.write_text(json.dumps(job), encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-c", _RUNNER, str(job_path)],
                capture_output=True,
                text=True,
                cwd=work,
                stdin=subprocess.DEVNULL,
                check=False,
                timeout=hard_timeout * len(pending) + 60,
            )
            stuck = result.returncode == _STUCK_EXIT
            stopped = f"exit {result.returncode}"
            stderr = result.stderr
        except subprocess.TimeoutExpired as exc:
            stuck = True
            stopped = "killed"
            raw = exc.stderr or ""
            stderr = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        done, step = _read_report(report_path)
        results.extend(done)
        if len(results) == len(entries):
            break
        assert step is not None, (
            f"the snippet runner stopped outside a file ({stopped}):\n{stderr[-4000:]}"
        )
        if stuck:
            failure = (
                f"{step['step']}: still running at {hard_timeout} seconds, "
                f"past the {timeout}-second timeout; the runner stopped it"
            )
        else:
            failure = (
                f"{step['step']}: the runner crashed ({stopped}): "
                f"{stderr[-2000:].strip()}"
            )
        results.append(
            {
                "file": pending[len(done)]["file"],
                "failure": failure,
                "not_run": step["not_run"],
            }
        )
    return results


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
