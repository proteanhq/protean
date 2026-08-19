"""Tests for the read-only ChangePlan preview renderer."""

import pytest

from protean.scaffold import (
    ChangePlan,
    ConfigOperation,
    CreateFileOperation,
    EditFileOperation,
    render_preview,
)

pytestmark = pytest.mark.no_test_domain


def _sample_plan(base: str) -> ChangePlan:
    """A plan whose paths point inside *base* (used by the no-write test)."""
    return ChangePlan(
        operations=(
            CreateFileOperation(
                path=f"{base}/new_file.py", content="first line\nsecond line"
            ),
            EditFileOperation(
                path=f"{base}/existing.py",
                diff="--- a/existing.py\n+++ b/existing.py\n@@ -1 +1 @@\n-old\n+new",
            ),
            ConfigOperation(
                key_path=("databases", "default", "provider"),
                value="postgresql",
                operation="merge",
            ),
        ),
        description="A sample change",
    )


def test_preview_names_each_target_path():
    text = render_preview(_sample_plan("app"))
    assert "app/new_file.py" in text
    assert "app/existing.py" in text


def test_preview_shows_the_unified_diff_for_an_edit():
    text = render_preview(_sample_plan("app"))
    assert "@@ -1 +1 @@" in text
    assert "-old" in text
    assert "+new" in text


def test_preview_renders_a_config_op_as_key_path_value_with_mode():
    text = render_preview(_sample_plan("app"))
    assert 'databases.default.provider = "postgresql"  (merge)' in text


def test_preview_shows_create_content_and_line_count():
    text = render_preview(
        ChangePlan(
            operations=(CreateFileOperation(path="a.py", content="one\ntwo\nthree"),)
        )
    )
    assert "create a.py  (3 lines)" in text
    assert "one" in text
    assert "three" in text


def test_preview_create_line_count_ignores_a_trailing_newline():
    # A full-content file normally ends in a trailing newline. The reported count
    # must match the rendered body lines: "a\nb\n" is two lines, not three.
    text = render_preview(
        ChangePlan(operations=(CreateFileOperation(path="a.py", content="a\nb\n"),))
    )
    assert "create a.py  (2 lines)" in text


def test_preview_of_an_empty_plan_renders_without_error():
    text = render_preview(ChangePlan())
    assert "(no operations)" in text


def test_preview_touches_no_files(tmp_path):
    """Rendering a plan whose ops point inside tmp_path writes nothing there."""
    plan = _sample_plan(str(tmp_path))

    def snapshot():
        return {
            p.relative_to(tmp_path).as_posix(): p.read_bytes()
            for p in sorted(tmp_path.rglob("*"))
            if p.is_file()
        }

    before = snapshot()
    text = render_preview(plan)
    after = snapshot()

    # The renderer produced output but changed nothing on disk.
    assert text
    assert before == after
    assert after == {}  # tmp_path started empty and stays empty
