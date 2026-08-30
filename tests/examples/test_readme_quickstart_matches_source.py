"""Guard test: the README Quick Start block must match the reference module.

The README cannot use pymdownx snippet markers (GitHub does not render
them), so this test gives it the same anti-drift protection by extracting
both sides and comparing them byte for byte:

- the fenced ```python``` block under the README's "## Quick Start" heading
- the region of ``examples/reference_app/blog.py`` marked with
  ``# --8<-- [start:quickstart]`` / ``# --8<-- [end:quickstart]``

It also runs the extracted README block in a subprocess to prove it is
copy-paste runnable and prints the expected write-then-read arc.
"""

import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_README_PATH = os.path.join(_REPO_ROOT, "README.md")
_BLOG_PATH = os.path.join(_REPO_ROOT, "examples", "reference_app", "blog.py")

_QUICKSTART_HEADING = "## Quick Start"
_START_MARKER = "# --8<-- [start:quickstart]"
_END_MARKER = "# --8<-- [end:quickstart]"


def _extract_readme_quickstart_block(readme_text: str) -> str:
    """Return the text inside the first fenced ```python block after the heading."""
    heading_count = readme_text.count(_QUICKSTART_HEADING)
    assert heading_count == 1, (
        f"Expected exactly one {_QUICKSTART_HEADING!r} heading in README.md, "
        f"found {heading_count}"
    )

    after_heading = readme_text.split(_QUICKSTART_HEADING, 1)[1]
    fence_count = after_heading.count("```python")
    assert fence_count == 1, (
        f"Expected exactly one fenced python block after {_QUICKSTART_HEADING!r}, "
        f"found {fence_count}"
    )

    _, remainder = after_heading.split("```python", 1)
    block, _, _ = remainder.partition("```")
    return block.strip("\n")


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
    lines = region.splitlines()
    assert lines and lines[0] == "", (
        "Expected a newline directly after the start marker"
    )
    return "\n".join(lines[1:]).strip("\n")


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
