"""Guard test: the README Quick Start block must match the reference module.

The README cannot use pymdownx snippet markers (GitHub does not render
them), so this test gives it equivalent anti-drift protection in CI by
extracting both sides and comparing them byte for byte:

- the fenced ```python``` block under the README's "## Quick Start" heading
- the region of ``examples/reference_app/blog.py`` marked with
  ``# --8<-- [start:quickstart]`` / ``# --8<-- [end:quickstart]``

It also runs the extracted README block in a subprocess to prove it is
copy-paste runnable and prints the expected write-then-read arc.
"""

import os
import re
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_README_PATH = os.path.join(_REPO_ROOT, "README.md")
_BLOG_PATH = os.path.join(_REPO_ROOT, "examples", "reference_app", "blog.py")

_QUICKSTART_HEADING = "## Quick Start"
_QUICKSTART_HEADING_RE = re.compile(r"^## Quick Start\s*$", re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^#{1,2} ", re.MULTILINE)
_START_MARKER = "# --8<-- [start:quickstart]"
_END_MARKER = "# --8<-- [end:quickstart]"


def _extract_readme_quickstart_block(readme_text: str) -> str:
    """Return the text inside the first fenced ```python block in the Quick Start section."""
    heading_matches = list(_QUICKSTART_HEADING_RE.finditer(readme_text))
    assert len(heading_matches) == 1, (
        f"Expected exactly one {_QUICKSTART_HEADING!r} heading line in README.md, "
        f"found {len(heading_matches)}"
    )

    section_start = heading_matches[0].end()
    next_heading = _NEXT_HEADING_RE.search(readme_text, section_start)
    section_end = next_heading.start() if next_heading else len(readme_text)
    section = readme_text[section_start:section_end]

    fence_count = section.count("```python")
    assert fence_count == 1, (
        f"Expected exactly one fenced python block in the {_QUICKSTART_HEADING!r} "
        f"section, found {fence_count}"
    )

    _, remainder = section.split("```python", 1)
    block, closing_fence, _ = remainder.partition("```")
    assert closing_fence, "Quick Start python block is missing its closing fence"
    assert block.startswith("\n"), (
        "Expected a newline directly after the ```python fence"
    )
    assert block.endswith("\n"), "Expected a newline directly before the closing fence"
    return block[1:-1]


def _extract_blog_quickstart_region(blog_text: str) -> str:
    """Return the text strictly between the start and end marker lines."""
    start_count = blog_text.count(_START_MARKER)
    end_count = blog_text.count(_END_MARKER)
    assert start_count == 1, (
        f"Expected exactly one {_START_MARKER!r} marker in blog.py, found {start_count}"
    )
    assert end_count == 1, (
        f"Expected exactly one {_END_MARKER!r} marker in blog.py, found {end_count}"
    )

    _, remainder = blog_text.split(_START_MARKER, 1)
    region, _, _ = remainder.partition(_END_MARKER)
    assert region.startswith("\n"), "Expected a newline directly after the start marker"
    assert region.endswith("\n"), "Expected a newline directly before the end marker"
    return region[1:-1]


@pytest.mark.no_test_domain
class TestReadmeQuickstartMatchesSource:
    @pytest.fixture()
    def readme_block(self) -> str:
        with open(_README_PATH, encoding="utf-8") as f:
            return _extract_readme_quickstart_block(f.read())

    @pytest.fixture()
    def blog_region(self) -> str:
        with open(_BLOG_PATH, encoding="utf-8") as f:
            return _extract_blog_quickstart_region(f.read())

    def test_extracted_blocks_are_non_empty_with_anchor_lines(
        self, readme_block, blog_region
    ):
        """A vacuous extractor (returning "") must not be able to pass the guard."""
        for block in (readme_block, blog_region):
            assert block, "Extracted block is empty"
            assert "from protean import Domain" in block
            assert "class PublishedPostsFeed" in block

    def test_quickstart_takes_current_domain_from_the_public_api(
        self, readme_block, blog_region
    ):
        """current_domain is public at the top level, so the snippet must import it there."""
        for block in (readme_block, blog_region):
            assert "from protean import Domain, current_domain, handle" in block
            assert "protean.utils.globals" not in block

    def test_readme_block_matches_blog_source_byte_for_byte(
        self, readme_block, blog_region
    ):
        assert readme_block == blog_region, (
            "README.md 'Quick Start' block has drifted from the marked region "
            "in examples/reference_app/blog.py. Re-copy the region between "
            f"{_START_MARKER!r} and {_END_MARKER!r} into the README verbatim."
        )

    def test_readme_block_runs_and_prints_the_arc(self, readme_block, tmp_path):
        script = tmp_path / "readme_quickstart.py"
        script.write_text(readme_block, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"README Quick Start block failed to run.\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert "Event handled: post published (Hello, Protean!)" in result.stdout
        assert "Post created: Hello, Protean! (status: PUBLISHED)" in result.stdout
        assert "Published posts feed: 1 row(s)" in result.stdout
        assert "  - Hello, Protean!" in result.stdout


@pytest.mark.no_test_domain
class TestExtractorsAreVerbatim:
    """The extractors must keep blank lines at the edges, or drift slips through."""

    def test_readme_extractor_keeps_edge_blank_lines(self):
        readme = "## Quick Start\n\n```python\n\nx = 1\n\n```\n"
        assert _extract_readme_quickstart_block(readme) == "\nx = 1\n"

    def test_blog_extractor_keeps_edge_blank_lines(self):
        blog = f"{_START_MARKER}\n\nx = 1\n\n{_END_MARKER}\n"
        assert _extract_blog_quickstart_region(blog) == "\nx = 1\n"

    def test_a_blank_line_only_difference_fails_the_comparison(self):
        readme = "## Quick Start\n\n```python\n\nx = 1\n```\n"
        blog = f"{_START_MARKER}\nx = 1\n{_END_MARKER}\n"
        assert _extract_readme_quickstart_block(
            readme
        ) != _extract_blog_quickstart_region(blog)

    def test_readme_extractor_rejects_an_unclosed_fence(self):
        with pytest.raises(AssertionError, match="closing fence"):
            _extract_readme_quickstart_block("## Quick Start\n\n```python\nx = 1\n")

    def test_readme_extractor_rejects_code_on_the_fence_line(self):
        with pytest.raises(AssertionError, match="newline directly after"):
            _extract_readme_quickstart_block("## Quick Start\n\n```pythonx = 1\n```\n")

    def test_blog_extractor_rejects_an_indented_end_marker(self):
        with pytest.raises(AssertionError, match="newline directly before"):
            _extract_blog_quickstart_region(
                f"{_START_MARKER}\nx = 1\n    {_END_MARKER}\n"
            )
