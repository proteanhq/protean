"""Check the snippet runner and include expander on synthetic pages.

``tests/docs/test_doc_pages_run.py`` runs the real documentation pages through
``tests/support/snippets.py``. These tests write small pages and included files
under ``tmp_path`` and run them through the same code.
"""

from __future__ import annotations

import signal
from pathlib import Path

import pytest

from tests.support.snippets import (
    FILE_TIMEOUT,
    Block,
    SnippetError,
    evaluate_one,
    extract_blocks,
    include_expander,
    parse_problems,
    read_include,
    run_snippets,
)

pytestmark = pytest.mark.no_test_domain

SECTIONED = (
    "import os\n"
    "# --8<-- [start:model]\n"
    "@domain.aggregate\n"
    "class Order:\n"
    "    name = String()\n"
    "# --8<-- [end:model]\n"
    "# --8<-- [start:other]\n"
    "VALUE = 2\n"
    "# --8<-- [end:other]\n"
)


@pytest.fixture
def bases(tmp_path: Path) -> tuple[Path, Path]:
    first = tmp_path / "docs_src"
    second = tmp_path / "examples"
    first.mkdir()
    second.mkdir()
    (first / "shop.py").write_text(SECTIONED, encoding="utf-8")
    (second / "extra.py").write_text("EXTRA = 1\n", encoding="utf-8")
    return first, second


def _write(tmp_path: Path, text: str, name: str = "page.md") -> Path:
    root = tmp_path / "docs"
    page = root / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding="utf-8")
    return page


def _run(
    tmp_path: Path, pages: list[Path], bases: tuple[Path, Path], timeout: float = 30.0
) -> list[dict]:
    return run_snippets(
        tmp_path / "docs",
        pages,
        tmp_path,
        timeout=timeout,
        expand=include_expander(bases),
    )


# --- Finding blocks ----------------------------------------------------------


def test_py_and_attributed_fences_are_found_and_other_languages_are_not():
    text = (
        "```py\na = 1\n```\n"
        '```python hl_lines="2" title="x.py"\nb = 2\n```\n'
        "~~~python\nc = 3\n~~~\n"
        "````python\nd = '```'\n````\n"
        "```pycon\n>>> e = 5\n```\n"
        "```ipython\nIn [1]: f = 6\n```\n"
        "```bash\ng=7\n```\n"
    )
    assert [b.source for b in extract_blocks(text)] == [
        "a = 1\n",
        "b = 2\n",
        "c = 3\n",
        "d = '```'\n",
    ]


def test_a_tilde_fence_is_closed_only_by_tildes():
    text = "~~~python\na = 1\n```\nb = 2\n~~~\n"
    assert [b.source for b in extract_blocks(text)] == ["a = 1\n```\nb = 2\n"]


def test_blocks_under_a_tab_and_an_admonition_are_dedented():
    text = (
        '=== "Tab"\n'
        "\n"
        "    ```python\n"
        "    class A:\n"
        "        x = 1\n"
        "    ```\n"
        "\n"
        "!!! note\n"
        "    ```python\n"
        "        # fragment\n"
        "        def f(self):\n"
        "    ```\n"
    )
    assert extract_blocks(text) == [
        Block(line=4, source="class A:\n    x = 1\n", fragment=False),
        Block(line=10, source="# fragment\ndef f(self):\n", fragment=True),
    ]


# --- Includes ----------------------------------------------------------------


def test_a_named_section_includes_its_lines_without_markers(bases):
    assert read_include("shop.py:model", bases) == (
        "@domain.aggregate\nclass Order:\n    name = String()"
    )


def test_a_whole_file_include_drops_the_section_markers(bases):
    assert read_include("shop.py", bases) == (
        "import os\n@domain.aggregate\nclass Order:\n    name = String()\nVALUE = 2"
    )


def test_a_line_range_counts_from_one_and_drops_the_section_markers(bases):
    # Lines 5 to 8: the field, the end and start markers, and VALUE.
    assert read_include("shop.py:5:8", bases) == "    name = String()\nVALUE = 2"


def test_a_line_range_past_the_end_stops_at_the_last_line(bases):
    assert read_include("shop.py:8:40", bases) == "VALUE = 2"


def test_the_second_base_path_is_searched(bases):
    assert read_include("extra.py", bases) == "EXTRA = 1"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("shop.py:1:2:3", "unknown include form 'shop.py:1:2:3'"),
        ("shop.py:", "unknown include form 'shop.py:'"),
        (":model", "unknown include form ':model'"),
        ("gone.py", "no file 'gone.py' under docs_src, examples"),
        (
            "shop.py:missing",
            "include 'shop.py:missing': no section 'missing' in shop.py",
        ),
        (
            "shop.py:20:30",
            "include 'shop.py:20:30' asks for lines 20 to 30, but shop.py has 9 lines",
        ),
        (
            "shop.py:0:2",
            "include 'shop.py:0:2' asks for lines 0 to 2, but shop.py has 9 lines",
        ),
        ("../outside.py", "no file '../outside.py' under docs_src, examples"),
    ],
)
def test_a_broken_include_raises_a_message_naming_it(bases, spec, message):
    with pytest.raises(SnippetError) as error:
        read_include(spec, bases)
    assert str(error.value) == message


def test_an_absolute_include_path_is_refused(tmp_path, bases):
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(SnippetError) as error:
        read_include(str(outside), bases)
    assert str(error.value) == f"no file {str(outside)!r} under docs_src, examples"


def test_a_relative_include_that_leaves_the_base_is_refused(tmp_path, bases):
    (tmp_path / "outside.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(SnippetError):
        read_include("../outside.py", bases)


def test_a_section_ends_at_its_first_end_marker(bases):
    (bases[0] / "twice.py").write_text(
        "# --8<-- [start:a]\nx = 1\n# --8<-- [end:a]\ny = 2\n# --8<-- [end:a]\n",
        encoding="utf-8",
    )
    assert read_include("twice.py:a", bases) == "x = 1"


def test_a_section_without_an_end_marker_raises(bases):
    (bases[0] / "open.py").write_text("# --8<-- [start:a]\nx = 1\n", encoding="utf-8")
    with pytest.raises(SnippetError) as error:
        read_include("open.py:a", bases)
    assert str(error.value) == "include 'open.py:a': section 'a' has no end marker"


def test_included_lines_take_the_include_lines_indent(bases):
    expand = include_expander(bases)
    block = Block(
        line=3,
        source='class Box:\n    --8<-- "extra.py"\n    size = 2\n',
        fragment=False,
    )
    assert expand(block) == Block(
        line=3, source="class Box:\n    EXTRA = 1\n    size = 2\n", fragment=False
    )


def test_an_indented_section_inside_a_class_keeps_both_indents(bases):
    (bases[0] / "methods.py").write_text(
        "class Real:\n"
        "    # --8<-- [start:m]\n"
        "    def size(self):\n"
        "        return 1\n"
        "    # --8<-- [end:m]\n",
        encoding="utf-8",
    )
    expand = include_expander(bases)
    block = Block(
        line=3, source='class Box:\n    --8<-- "methods.py:m"\n', fragment=False
    )
    assert expand(block).source == (
        "class Box:\n        def size(self):\n            return 1\n"
    )


def test_a_block_of_only_an_indented_section_is_not_dedented(tmp_path, bases):
    (bases[0] / "methods.py").write_text(
        "class Real:\n"
        "    # --8<-- [start:m]\n"
        "    def size(self):\n"
        "        return 1\n"
        "    # --8<-- [end:m]\n",
        encoding="utf-8",
    )
    expand = include_expander(bases)
    block = Block(line=2, source='--8<-- "methods.py:m"\n', fragment=False)
    assert expand(block).source == "    def size(self):\n        return 1\n"
    page = _write(tmp_path, '```python\n--8<-- "methods.py:m"\n```\n')
    assert parse_problems(page, "page.md", expand) == [
        "page.md: line 2: SyntaxError on line 1 of the block: unexpected indent"
    ]


@pytest.mark.parametrize(
    "line",
    [
        "--8<-- 'extra.py'",
        '-8<- "extra.py"',
        ';--8<-- "extra.py"',
        "--8<--",
        '    ---8<--- "extra.py"',
    ],
)
def test_an_include_line_in_another_form_raises(bases, line):
    expand = include_expander(bases)
    with pytest.raises(SnippetError) as error:
        expand(Block(line=2, source=f"x = 1\n{line}\n", fragment=False))
    assert str(error.value) == f"unknown include form {line.strip()!r}"


def test_an_include_line_in_another_form_is_a_parse_problem(tmp_path, bases):
    page = _write(tmp_path, "```python\nx = 1\n--8<-- 'extra.py'\n```\n")
    assert parse_problems(page, "page.md", include_expander(bases)) == [
        "page.md: line 2: unknown include form \"--8<-- 'extra.py'\""
    ]


def test_the_fragment_marker_comes_from_the_page_not_the_include(bases):
    (bases[0] / "marked.py").write_text("# fragment\nx = 1\n", encoding="utf-8")
    expand = include_expander(bases)
    included = expand(Block(line=2, source='--8<-- "marked.py"\n', fragment=False))
    assert included.fragment is False
    marked = expand(
        Block(line=2, source='# fragment\n--8<-- "extra.py"\n', fragment=True)
    )
    assert marked == Block(line=2, source="# fragment\nEXTRA = 1\n", fragment=True)


# --- The parse check ---------------------------------------------------------


def test_a_repl_transcript_in_a_python_fence_is_a_problem(tmp_path, bases):
    page = _write(tmp_path, "Text.\n```python\n>>> x = 1\n```\n")
    assert parse_problems(page, "page.md", include_expander(bases)) == [
        "page.md: line 3: a '>>>' transcript; fence it as 'pycon', not 'python'"
    ]
    page.write_text("Text.\n```pycon\n>>> x = 1\n```\n", encoding="utf-8")
    assert parse_problems(page, "page.md", include_expander(bases)) == []


def test_a_block_that_does_not_parse_is_a_problem_unless_a_fragment(tmp_path, bases):
    page = _write(
        tmp_path,
        "```python\nx = 1\n```\n"
        "```python\ndef f(self, ...): ...\n```\n"
        "```python\n# fragment\ndef g(self, ...): ...\n```\n",
    )
    assert parse_problems(page, "page.md", include_expander(bases)) == [
        "page.md: line 5: SyntaxError on line 1 of the block: invalid syntax"
    ]


def test_a_broken_include_is_a_parse_problem_naming_the_page(tmp_path, bases):
    page = _write(tmp_path, 'Text.\n```python\n--8<-- "shop.py:nope"\n```\n')
    assert parse_problems(page, "page.md", include_expander(bases)) == [
        "page.md: line 3: include 'shop.py:nope': no section 'nope' in shop.py"
    ]


# --- Running pages -----------------------------------------------------------


def test_a_page_runs_includes_and_inline_blocks_in_one_namespace(tmp_path, bases):
    page = _write(
        tmp_path,
        "# Page\n"
        '--8<-- "gone.py"\n'
        "```python\n"
        '--8<-- "shop.py:model"\n'
        "```\n"
        "```python\n"
        "@domain.event(part_of=Order)\n"
        "class OrderPlaced:\n"
        "    name = String()\n"
        "```\n"
        "```python\n"
        "assert OrderPlaced.meta_.part_of is Order\n"
        "```\n",
    )
    # The include line outside a fence names a missing file and is ignored.
    assert _run(tmp_path, [page], bases) == [
        {"file": "page.md", "failure": None, "not_run": []}
    ]


def test_a_raising_block_names_the_page_line_and_blocks_not_run(tmp_path, bases):
    page = _write(
        tmp_path,
        "```python\nx = 1\n```\n"
        "```python\nraise ValueError('boom')\n```\n"
        "```python\ny = 2\n```\n",
    )
    (result,) = _run(tmp_path, [page], bases)
    assert evaluate_one(result, frozenset()) == [
        "page.md: line 5: ValueError: boom; not run: blocks at lines 8"
    ]


def test_a_broken_include_fails_the_page_and_runs_nothing(tmp_path, bases):
    page = _write(
        tmp_path,
        "```python\nraise ValueError('never run')\n```\n"
        '```python\n--8<-- "shop.py:1:2:3"\n```\n',
    )
    (result,) = _run(tmp_path, [page], bases)
    assert result == {
        "file": "page.md",
        "failure": "line 5: unknown include form 'shop.py:1:2:3'",
        "not_run": [2, 5],
    }


def test_a_fragment_is_skipped_and_the_blocks_after_it_run(tmp_path, bases):
    page = _write(
        tmp_path,
        "```python\n# fragment\nmarker = 1\nraise ValueError('never run')\n```\n"
        "```python\nassert 'marker' not in globals()\nseen = True\n```\n"
        "```python\nassert seen\n```\n",
    )
    assert _run(tmp_path, [page], bases)[0]["failure"] is None


def test_blocks_under_a_tab_and_an_admonition_run(tmp_path, bases):
    page = _write(
        tmp_path,
        '=== "Tab"\n\n    ```python\n    total = 2\n    ```\n\n'
        "!!! note\n    ```python\n    assert total == 2\n    ```\n",
    )
    assert _run(tmp_path, [page], bases)[0]["failure"] is None


def test_a_page_that_binds_its_own_domain_has_it_initialized(tmp_path, bases):
    page = _write(
        tmp_path,
        "```python\n"
        "domain = Domain(name='Mine')\n"
        "@domain.event(part_of='Missing')\n"
        "class Happened:\n"
        "    x = String()\n"
        "```\n",
    )
    failure = _run(tmp_path, [page], bases)[0]["failure"]
    assert failure.startswith("init: ConfigurationError: ")
    assert "`Happened` references `Missing` via part_of" in failure


def test_a_domain_that_registers_nothing_is_not_initialized(tmp_path, bases):
    page = _write(
        tmp_path,
        "```python\n"
        "class Strict(Domain):\n"
        "    def init(self, traverse=True):\n"
        "        raise RuntimeError('init ran')\n"
        "\n"
        "empty = Strict(name='Empty')\n"
        "```\n",
    )
    assert _run(tmp_path, [page], bases)[0]["failure"] is None


def test_a_domain_that_registers_an_element_is_initialized(tmp_path, bases):
    page = _write(
        tmp_path,
        "```python\n"
        "class Strict(Domain):\n"
        "    def init(self, traverse=True):\n"
        "        raise RuntimeError('init ran')\n"
        "\n"
        "full = Strict(name='Full')\n"
        "\n"
        "@full.aggregate\n"
        "class Thing:\n"
        "    name = String()\n"
        "```\n",
    )
    assert _run(tmp_path, [page], bases)[0]["failure"] == (
        "init: RuntimeError: init ran"
    )


def test_a_domain_context_a_page_leaves_open_is_closed_before_the_next_page(
    tmp_path, bases
):
    opener = _write(
        tmp_path,
        "```python\n"
        "from protean.utils.globals import current_domain\n"
        "domain.domain_context().push()\n"
        "assert current_domain.name == domain.name\n"
        "```\n",
        name="a.md",
    )
    reader = _write(
        tmp_path,
        "```python\n"
        "from protean.utils.globals import current_domain\n"
        "assert not current_domain, current_domain.name\n"
        "```\n",
        name="b.md",
    )
    assert _run(tmp_path, [opener, reader], bases) == [
        {"file": "a.md", "failure": None, "not_run": []},
        {"file": "b.md", "failure": None, "not_run": []},
    ]


def test_a_unit_of_work_a_page_leaves_open_is_cleared_before_the_next_page(
    tmp_path, bases
):
    opener = _write(
        tmp_path,
        "```python\n"
        "from protean.utils.globals import current_uow\n"
        "domain.init(traverse=False)\n"
        "with domain.domain_context():\n"
        "    UnitOfWork().start()\n"
        "assert current_uow\n"
        "```\n",
        name="a.md",
    )
    reader = _write(
        tmp_path,
        "```python\n"
        "from protean.utils.globals import current_uow\n"
        "assert not current_uow\n"
        "```\n",
        name="b.md",
    )
    assert _run(tmp_path, [opener, reader], bases) == [
        {"file": "a.md", "failure": None, "not_run": []},
        {"file": "b.md", "failure": None, "not_run": []},
    ]


def test_an_allowlisted_page_that_passes_says_to_remove_the_entry(tmp_path, bases):
    page = _write(tmp_path, "```python\nx = 1\n```\n")
    (result,) = _run(tmp_path, [page], bases)
    assert evaluate_one(result, frozenset({"page.md"})) == [
        "page.md: every block passes; remove 'page.md' from the allowlist"
    ]


@pytest.mark.skipif(
    not hasattr(signal, "setitimer"), reason="the per-page timeout needs SIGALRM"
)
def test_a_page_past_the_timeout_is_reported_and_the_next_page_runs(tmp_path, bases):
    slow = _write(tmp_path, "```python\nimport time\ntime.sleep(30)\n```\n", "a.md")
    after = _write(tmp_path, "```python\nraise ValueError('b ran')\n```\n", "b.md")
    assert _run(tmp_path, [slow, after], bases, timeout=0.5) == [
        {
            "file": "a.md",
            "failure": "line 2: timed out after 0.5 seconds",
            "not_run": [],
        },
        {"file": "b.md", "failure": "line 2: ValueError: b ran", "not_run": []},
    ]


def test_the_per_file_timeout_is_thirty_seconds():
    assert FILE_TIMEOUT == 30.0


def test_a_page_that_catches_the_timeout_is_stopped_and_the_next_page_runs(
    tmp_path, bases
):
    stuck = _write(
        tmp_path,
        "```python\n"
        "import time\n"
        "while True:\n"
        "    try:\n"
        "        time.sleep(10)\n"
        "    except BaseException:\n"
        "        pass\n"
        "```\n"
        "```python\nlater = 1\n```\n",
        "a.md",
    )
    after = _write(tmp_path, "```python\nraise ValueError('b ran')\n```\n", "b.md")
    assert _run(tmp_path, [stuck, after], bases, timeout=0.5) == [
        {
            "file": "a.md",
            "failure": (
                "line 2: still running at 1.0 seconds, past the 0.5-second "
                "timeout; the runner stopped it"
            ),
            "not_run": [10],
        },
        {"file": "b.md", "failure": "line 2: ValueError: b ran", "not_run": []},
    ]


def test_a_page_that_crashes_the_runner_is_reported_and_the_next_page_runs(
    tmp_path, bases
):
    first = _write(tmp_path, "```python\nfirst = 1\n```\n", "a.md")
    crash = _write(
        tmp_path,
        "```python\nimport os\nos._exit(5)\n```\n```python\nlater = 1\n```\n",
        "b.md",
    )
    after = _write(tmp_path, "```python\nraise ValueError('c ran')\n```\n", "c.md")
    results = _run(tmp_path, [first, crash, after], bases)
    assert [r["file"] for r in results] == ["a.md", "b.md", "c.md"]
    assert results[0]["failure"] is None
    assert results[1]["failure"].startswith("line 2: the runner crashed (exit 5)")
    assert results[1]["not_run"] == [6]
    assert results[2] == {
        "file": "c.md",
        "failure": "line 2: ValueError: c ran",
        "not_run": [],
    }
