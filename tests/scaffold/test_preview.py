"""Tests for the read-only ChangePlan preview renderer."""

import pytest

from protean.scaffold import (
    OWNERSHIP_GENERATED,
    OWNERSHIP_HAND_OWNED,
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


def test_preview_sorts_the_keys_of_a_dict_config_value():
    # Previews get diffed, so a dict value must render the same way whatever
    # order the producer built it in.
    def render(value):
        return render_preview(
            ChangePlan(
                operations=(ConfigOperation(key_path=("databases",), value=value),)
            )
        )

    text = render({"provider": "postgresql", "database_uri": "postgresql://"})

    assert '{"database_uri": "postgresql://", "provider": "postgresql"}' in text
    assert text == render({"database_uri": "postgresql://", "provider": "postgresql"})


def test_preview_shows_create_content_and_line_count():
    text = render_preview(
        ChangePlan(
            operations=(CreateFileOperation(path="a.py", content="one\ntwo\nthree"),)
        )
    )
    assert "create a.py  (3 lines, hand-owned)" in text
    assert "one" in text
    assert "three" in text


def test_preview_create_line_count_ignores_a_trailing_newline():
    # A full-content file normally ends in a trailing newline. The reported count
    # must match the rendered body lines: "a\nb\n" is two lines, not three.
    text = render_preview(
        ChangePlan(operations=(CreateFileOperation(path="a.py", content="a\nb\n"),))
    )
    assert "create a.py  (2 lines, hand-owned)" in text


def test_every_ownership_value_has_a_preview_label():
    # The preview's label map is a hand-maintained mirror of the model's allowed
    # ownership values. Diff the two so a value added to the model without a label
    # fails here loudly, instead of the preview mislabeling that file and quietly
    # telling a user the wrong thing about what a re-run would touch.
    from protean.scaffold.change_plan import _OWNERSHIP_VALUES
    from protean.scaffold.preview import _OWNERSHIP_LABELS

    assert set(_OWNERSHIP_LABELS) == _OWNERSHIP_VALUES


def test_preview_labels_a_create_op_with_its_ownership():
    # The seam (ADR-0035) is visible in the preview: a "generated" file a re-run
    # of add would refresh reads differently from a "hand-owned" one it leaves.
    text = render_preview(
        ChangePlan(
            operations=(
                CreateFileOperation(
                    path="base.py", content="x", ownership=OWNERSHIP_GENERATED
                ),
                CreateFileOperation(
                    path="logic.py", content="y", ownership=OWNERSHIP_HAND_OWNED
                ),
            )
        )
    )
    assert "create base.py  (1 lines, generated)" in text
    assert "create logic.py  (1 lines, hand-owned)" in text


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
