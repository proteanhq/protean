"""Tests for the optional-dependency message builder (ADR-0029)."""

from protean.utils.dependencies import missing_dependency_message


def test_message_names_the_package_extra_and_feature():
    msg = missing_dependency_message("copier", "scaffold", "'protean new'")

    assert "copier" in msg
    assert "'protean new'" in msg
    # The literal install command must survive intact, including the bracketed
    # extra — this is what the caller pastes into a terminal.
    assert 'pip install "protean[scaffold]"' in msg


def test_message_is_a_single_actionable_line_per_extra():
    for package, extra in [
        ("fastapi", "server"),
        ("IPython", "shell"),
        ("copier", "scaffold"),
    ]:
        msg = missing_dependency_message(package, extra, "a feature")
        assert msg.startswith("a feature requires the")
        assert f"protean[{extra}]" in msg
