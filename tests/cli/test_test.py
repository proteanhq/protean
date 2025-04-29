import subprocess
from unittest.mock import Mock, call

import pytest
import typer
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.test import TestCategory

runner = CliRunner(mix_stderr=True)


@pytest.fixture
def mock_subprocess_call(mocker):
    mock_call = mocker.patch("protean.cli.test.subprocess.call")
    mock_call.return_value = 0
    return mock_call


@pytest.mark.parametrize(
    "category,expected_calls,call_count",
    [
        (
            TestCategory.EVENTSTORE,
            [
                call(
                    [
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "eventstore",
                        "--store=MEMORY",
                    ]
                ),
                call(
                    [
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "eventstore",
                        "--store=MESSAGE_DB",
                    ]
                ),
            ],
            2,
        ),
        (
            TestCategory.DATABASE,
            [
                call(
                    [
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=MEMORY",
                    ]
                ),
                call(
                    [
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=POSTGRESQL",
                    ]
                ),
                call(
                    [
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=SQLITE",
                    ]
                ),
            ],
            3,
        ),
        (
            TestCategory.FULL,
            [
                call(["coverage", "erase"]),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "--slow",
                        "--sqlite",
                        "--postgresql",
                        "--elasticsearch",
                        "--redis",
                        "--message_db",
                        "tests",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=MEMORY",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=POSTGRESQL",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=SQLITE",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "eventstore",
                        "--store=MESSAGE_DB",
                    ]
                ),
                call(["coverage", "combine"]),
                call(["coverage", "xml"]),
                call(["coverage", "report"]),
            ],
            9,  # 5 calls + 4 for coverage operations (erase, combine, report)
        ),
        (
            TestCategory.COVERAGE,
            [
                call(["coverage", "erase"]),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "--slow",
                        "--sqlite",
                        "--postgresql",
                        "--elasticsearch",
                        "--redis",
                        "--message_db",
                        "tests",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=MEMORY",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=POSTGRESQL",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "database",
                        "--db=SQLITE",
                    ]
                ),
                call(
                    [
                        "coverage",
                        "run",
                        "--parallel-mode",
                        "-m",
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "-m",
                        "eventstore",
                        "--store=MESSAGE_DB",
                    ]
                ),
                call(["coverage", "combine"]),
                call(["coverage", "xml"]),
                call(["coverage", "report"]),
                call(
                    [
                        "diff-cover",
                        "coverage.xml",
                        "--compare-branch=main",
                        "--html-report",
                        "diff_coverage_report.html",
                    ]
                ),
            ],
            10,  # Updated count: 9 calls from run_full + 1 for diff-cover
        ),
        (
            TestCategory.CORE,
            [
                call(["pytest", "--cache-clear", "--ignore=tests/support/"]),
            ],
            1,
        ),
    ],
)
def test_command(
    mock_subprocess_call, category, expected_calls, call_count, monkeypatch
):
    # Mock webbrowser.open so we don't open the report in the browser
    mock_webbrowser_open = Mock()
    monkeypatch.setattr("webbrowser.open", mock_webbrowser_open)

    result = runner.invoke(
        app, ["test", "--category", category.value], standalone_mode=False
    )

    assert result.exit_code == 0
    assert mock_subprocess_call.call_count == call_count
    mock_subprocess_call.assert_has_calls(expected_calls, any_order=True)


def test_default_category(mock_subprocess_call):
    # Test the command with the default category (CORE)
    result = runner.invoke(app, ["test"], standalone_mode=False)

    assert result.exit_code == 0
    mock_subprocess_call.assert_called_once_with(
        ["pytest", "--cache-clear", "--ignore=tests/support/"]
    )


def test_invalid_category(mock_subprocess_call):
    # Test the command with an invalid category (should raise error)
    result = runner.invoke(
        app, ["test", "--category", "INVALID"], standalone_mode=False
    )

    assert result.exit_code == 1
    assert (
        str(result.exception)
        == "'INVALID' is not one of 'CORE', 'EVENTSTORE', 'DATABASE', 'COVERAGE', 'FULL'."
    )


class TestInjectStyle:
    def test_inject_style_success(self, tmp_path):
        """Test successful style injection into HTML file."""
        from protean.cli.test import STYLE_BLOCK, _inject_style

        # Create a test HTML file with a head section
        test_html = tmp_path / "test.html"
        test_html.write_text("<html><head></head><body>content</body></html>")

        # Call the function
        _inject_style(test_html)

        # Verify the style was injected
        content = test_html.read_text()
        assert STYLE_BLOCK in content
        assert content.find(STYLE_BLOCK) < content.find("</head>")
        assert content.endswith("<body>content</body></html>")

    def test_inject_style_already_injected(self, tmp_path):
        """Test injection when style is already present."""
        from protean.cli.test import STYLE_BLOCK, _inject_style

        # Create a test HTML file that already has the style block
        test_html = tmp_path / "test.html"
        test_html.write_text(
            f"<html><head>{STYLE_BLOCK}</head><body>content</body></html>"
        )

        # Get the original content for comparison
        original_content = test_html.read_text()

        # Call the function
        _inject_style(test_html)

        # Verify the file wasn't modified
        assert test_html.read_text() == original_content

    def test_inject_style_no_head(self, tmp_path):
        """Test injection with no </head> tag."""
        from protean.cli.test import _inject_style

        # Create a test HTML file without a head closing tag
        test_html = tmp_path / "test.html"
        test_html.write_text("<html><body>content</body></html>")

        # Get the original content for comparison
        original_content = test_html.read_text()

        # Call the function
        _inject_style(test_html)

        # Verify the file wasn't modified
        assert test_html.read_text() == original_content

    def test_inject_style_file_not_found(self):
        """Test injection when file doesn't exist."""
        from pathlib import Path

        from protean.cli.test import _inject_style

        # Try to inject into a non-existent file
        nonexistent_file = Path("nonexistent_file.html")

        # This should not raise an exception due to suppress(FileNotFoundError)
        _inject_style(nonexistent_file)

    def test_inject_style_custom_block(self, tmp_path):
        """Test injection with a custom style block."""
        from protean.cli.test import _inject_style

        # Create a test HTML file
        test_html = tmp_path / "test.html"
        test_html.write_text("<html><head></head><body>content</body></html>")

        # Custom style block
        custom_style = "<style>body { color: blue; }</style>"

        # Call the function with custom style
        _inject_style(test_html, custom_style)

        # Verify the custom style was injected
        content = test_html.read_text()
        assert custom_style in content
        assert content.find(custom_style) < content.find("</head>")


class TestRunFull:
    def test_run_full_success(self, mock_subprocess_call):
        """Test run_full with all tests passing (line 135 where exit_status == 0)."""
        from protean.cli.test import run_full

        # Configure the mock to indicate all commands succeeded
        mock_subprocess_call.return_value = 0

        # Run the function
        exit_status = run_full(
            subprocess,
            ["coverage", "run", "--parallel-mode", "-m"],
            ["pytest", "--cache-clear", "--ignore=tests/support/"],
        )

        # Verify all expected commands were called
        assert mock_subprocess_call.call_count == 9
        assert exit_status == 0

        # Verify coverage combine commands were called (happens when exit_status == 0)
        mock_subprocess_call.assert_any_call(["coverage", "combine"])
        mock_subprocess_call.assert_any_call(["coverage", "xml"])
        mock_subprocess_call.assert_any_call(["coverage", "report"])

    def test_run_full_with_failures(self, mock_subprocess_call):
        """Test run_full with some tests failing (line 135 where exit_status != 0)."""
        from protean.cli.test import run_full

        # Configure the mock to indicate some commands failed
        # First call (erase) succeeds, second call (full test run) fails
        mock_subprocess_call.side_effect = [0, 1] + [0] * 10

        # Run the function
        exit_status = run_full(
            subprocess,
            ["coverage", "run", "--parallel-mode", "-m"],
            ["pytest", "--cache-clear", "--ignore=tests/support/"],
        )

        # Verify the function returned non-zero exit status
        assert exit_status != 0

        # Verify coverage combine commands were NOT called
        # (this is the branch we want to test, when failures occur)
        for cmd in [
            ["coverage", "combine"],
            ["coverage", "xml"],
            ["coverage", "report"],
        ]:
            assert call(cmd) not in mock_subprocess_call.call_args_list


class TestExitHandling:
    def test_category_coverage_success(self, mock_subprocess_call, monkeypatch):
        """Test COVERAGE category with success (line 183 where rc == 0)."""
        from protean.cli.test import REPORT_PATH

        # Setup mocks
        mock_subprocess_call.return_value = 0

        # Mock webbrowser.open instead of subprocess.call for opening the report
        mock_webbrowser_open = Mock()
        monkeypatch.setattr("webbrowser.open", mock_webbrowser_open)

        # Mock _inject_style to avoid file operations
        monkeypatch.setattr("protean.cli.test._inject_style", lambda *args: None)

        # Run the test command with COVERAGE category
        result = runner.invoke(
            app, ["test", "--category", "COVERAGE"], standalone_mode=False
        )

        # Verify exit code is 0
        assert result.exit_code == 0

        # Verify diff-cover was called
        mock_subprocess_call.assert_any_call(
            [
                "diff-cover",
                "coverage.xml",
                "--compare-branch=main",
                "--html-report",
                REPORT_PATH.name,
            ]
        )

        # Verify webbrowser.open was called instead of subprocess.call
        called_arg = mock_webbrowser_open.call_args[0][0]
        assert called_arg.endswith(REPORT_PATH.name)

    def test_category_coverage_with_failure(self, mock_subprocess_call, monkeypatch):
        """Test COVERAGE category with failure (line 183 where rc != 0)."""
        from protean.cli.test import test

        # Setup mocks to simulate a test failure in run_full
        # We need to control what run_full returns
        def mock_run_full(*args, **kwargs):
            return 1  # Return non-zero to simulate failure

        monkeypatch.setattr("protean.cli.test.run_full", mock_run_full)

        # Mock the print function to capture output
        printed_messages = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *args: printed_messages.append(" ".join(str(a) for a in args)),
        )

        # Running with failures should raise typer.Exit
        with pytest.raises(typer.Exit) as excinfo:
            test(category=TestCategory.COVERAGE)

        # Verify exit code is non-zero (line 190)
        assert excinfo.value.exit_code != 0

        # Check if the error message was printed
        assert "❌ Tests failed – skipping diff-cover report." in " ".join(
            printed_messages
        )

    def test_exit_with_error_code(self, mock_subprocess_call, monkeypatch):
        """Test exiting with non-zero status (line 190)."""

        # Configure subprocess.call to return non-zero to trigger the exception
        def mock_run(*args):
            return 1  # Return error code

        monkeypatch.setattr("protean.cli.test._run", mock_run)

        # This should raise typer.Exit with code=1
        with pytest.raises(typer.Exit) as excinfo:
            from protean.cli.test import test

            test(category=TestCategory.CORE)

        # Verify the exit code matches what the subprocess returned
        assert excinfo.value.exit_code == 1
