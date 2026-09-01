"""Guard test: the docs quickstart must stay single-sourced from blog.py.

``docs/guides/getting-started/quickstart.md`` pulls every code block from
``examples/reference_app/blog.py`` with pymdownx ``--8<--`` section includes,
and its "Run it" shell block is a copy of what the module prints. CI builds
the docs only on the ``main`` deploy, so these checks run on the PR gate
instead:

- every ``--8<--`` include targets the reference module;
- every named section it pulls has a real ``[start:...]`` / ``[end:...]``
  region in blog.py, so a renamed marker fails here rather than on deploy;
- each pulled region still encloses the element the page describes, so a
  moved marker cannot mis-slice a step;
- the "Run it" block matches what blog.py actually prints to stdout;
- the page no longer references the removed ``docs_src`` module.
"""

import os
import re
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DOC_PATH = os.path.join(
    _REPO_ROOT, "docs", "guides", "getting-started", "quickstart.md"
)
_BLOG_PATH = os.path.join(_REPO_ROOT, "examples", "reference_app", "blog.py")

_REMOVED_SOURCE = "guides/getting-started/quickstart.py"
_MODULE_PREFIX = "reference_app/blog.py:"
_SNIPPET_INCLUDE_RE = re.compile(r'--8<--\s*"([^"]+)"')
_RUN_COMMAND_LINE = "$ python blog.py"

# One region per pulled section, keyed by its marker name. Each entry lists
# lines that must appear in the region and lines that must not, so a marker
# moved across a class boundary (truncating a step or spilling into the next)
# fails here. The docs page pulls the whole module through ``quickstart``.
_SECTION_ANCHORS = {
    "imports": (
        ["from protean import Domain", "domain = Domain()"],
        ["@domain.aggregate"],
    ),
    "aggregate": (
        ["class Post:", "def publish(self):"],
        ["class PostPublished", "class PublishPost"],
    ),
    "event": (
        ["class PostPublished:"],
        ["class Post:", "class PublishPost"],
    ),
    "command": (
        ["class PublishPost:", "class PostCommandHandler:"],
        ["class PostEventHandler"],
    ),
    "event_handler": (
        ["class PostEventHandler:"],
        ["class PublishPost:", "class PublishedPostsFeed"],
    ),
    "projection": (
        ["class PublishedPostsFeed:", "class PublishedPostsFeedProjector:"],
        ['if __name__ == "__main__":'],
    ),
    "usage": (
        ['if __name__ == "__main__":', "domain.process("],
        ["@domain.aggregate"],
    ),
}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _snippet_includes(doc_text: str) -> list[str]:
    """Every ``--8<-- "path:section"`` target on the page, in order."""
    return _SNIPPET_INCLUDE_RE.findall(doc_text)


_START_MARKER_RE = re.compile(r"^# --8<-- \[start:([a-z][\w-]*)\]$", re.MULTILINE)


def _blog_sections(blog_text: str) -> dict[str, str]:
    """Map each ``[start:name]`` / ``[end:name]`` region to its inner text.

    Regions nest (``quickstart`` wraps every other), so each ``start`` marker
    is paired with its own ``end`` marker independently rather than with a
    single non-overlapping scan.
    """
    sections: dict[str, str] = {}
    for match in _START_MARKER_RE.finditer(blog_text):
        name = match.group(1)
        rest = blog_text[match.end() :]
        end = re.search(rf"^# --8<-- \[end:{re.escape(name)}\]$", rest, re.MULTILINE)
        assert end is not None, f"blog.py has [start:{name}] but no [end:{name}]"
        body = rest[: end.start()]
        sections[name] = body[1:] if body.startswith("\n") else body
    return sections


def _documented_output(shell_block: str) -> list[str]:
    """Program-output lines in a ```shell block, dropping the ``$`` prompt."""
    return [line for line in shell_block.splitlines() if not line.startswith("$")]


def _extract_run_shell_block(doc_text: str) -> str:
    """Return the text inside the single fenced ```shell block on the page."""
    fence = "```shell"
    count = doc_text.count(fence)
    assert count == 1, f"Expected exactly one ```shell block, found {count}"

    _, remainder = doc_text.split(fence, 1)
    block, closing, _ = remainder.partition("```")
    assert closing, "The ```shell block is missing its closing fence"
    return block.strip("\n")


@pytest.mark.no_test_domain
class TestDocsQuickstartSingleSourced:
    @pytest.fixture()
    def doc_text(self) -> str:
        return _read(_DOC_PATH)

    @pytest.fixture()
    def blog_text(self) -> str:
        return _read(_BLOG_PATH)

    def test_every_snippet_comes_from_the_reference_module(self, doc_text):
        """All code blocks pull from examples/reference_app/blog.py."""
        includes = _snippet_includes(doc_text)
        assert len(includes) > 0, "The quickstart page pulls no snippets"
        for target in includes:
            assert target.startswith(_MODULE_PREFIX), (
                f"Snippet {target!r} does not come from the reference module"
            )

    def test_every_referenced_section_exists_in_the_module(self, doc_text, blog_text):
        """Each pulled section has real markers, so a rename fails on the PR.

        Without this the failure would only surface on the main-only docs
        deploy, where pymdownx raises SnippetMissingError.
        """
        sections = _blog_sections(blog_text)
        includes = _snippet_includes(doc_text)
        assert len(includes) > 0, "The quickstart page pulls no snippets"
        for target in includes:
            section = target[len(_MODULE_PREFIX) :]
            assert section in sections, (
                f"quickstart.md pulls {section!r} but blog.py has no matching "
                f"[start:{section}] / [end:{section}] markers"
            )
            assert sections[section].strip(), f"Section {section!r} in blog.py is empty"

    def test_each_pulled_section_encloses_its_element(self, blog_text):
        """A moved marker that mis-slices a documented step fails here."""
        sections = _blog_sections(blog_text)
        for name, (present, absent) in _SECTION_ANCHORS.items():
            assert name in sections, f"blog.py is missing the {name!r} section"
            body = sections[name]
            for line in present:
                assert line in body, f"Section {name!r} no longer contains {line!r}"
            for line in absent:
                assert line not in body, f"Section {name!r} has spilled into {line!r}"

    def test_page_does_not_reference_the_removed_source(self, doc_text):
        """The quickstart page no longer references the old docs_src module."""
        assert _REMOVED_SOURCE not in doc_text

    def test_run_output_block_matches_the_module_stdout(self, doc_text):
        """The 'Run it' block is exactly what blog.py prints to stdout."""
        result = subprocess.run(
            [sys.executable, _BLOG_PATH],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"blog.py failed to run.\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

        shell_block = _extract_run_shell_block(doc_text)
        assert _RUN_COMMAND_LINE in shell_block.splitlines(), (
            f"The 'Run it' block should invoke the example as {_RUN_COMMAND_LINE!r}"
        )
        documented_output = _documented_output(shell_block)
        assert documented_output, "The 'Run it' block shows no output lines"
        assert documented_output == result.stdout.splitlines(), (
            "The quickstart 'Run it' block has drifted from what "
            "examples/reference_app/blog.py prints. Re-copy the module's stdout."
        )


class TestExtractorsAreHonest:
    """The extractors must not pass on empty or malformed input."""

    def test_run_block_extractor_requires_a_closing_fence(self):
        with pytest.raises(AssertionError, match="closing fence"):
            _extract_run_shell_block("Run it:\n\n```shell\n$ python blog.py\n")

    def test_run_block_extractor_requires_exactly_one_block(self):
        with pytest.raises(AssertionError, match="exactly one"):
            _extract_run_shell_block("no shell block here")

    def test_snippet_include_regex_finds_targets(self):
        doc = '```python\n--8<-- "reference_app/blog.py:aggregate"\n```\n'
        assert _snippet_includes(doc) == ["reference_app/blog.py:aggregate"]

    def test_documented_output_drops_only_the_prompt_line(self):
        shell_block = "$ python blog.py\nfirst line\n  - indented"
        assert _documented_output(shell_block) == ["first line", "  - indented"]

    def test_blog_sections_reads_nested_regions(self):
        blog = (
            "# --8<-- [start:quickstart]\n"
            "# --8<-- [start:aggregate]\n"
            "class Post:\n"
            "    pass\n"
            "# --8<-- [end:aggregate]\n"
            "# --8<-- [end:quickstart]\n"
        )
        sections = _blog_sections(blog)
        assert sections["aggregate"] == "class Post:\n    pass\n"
        assert "aggregate" in sections and "quickstart" in sections
