import subprocess
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.test import TEST_CONFIGS, RunCategory, TestRunner, TestSuite


@pytest.fixture
def mock_runner():
    """Fixture providing a TestRunner with mocked subprocess calls."""
    runner = TestRunner()
    with patch.object(runner, "run_command", return_value=0):
        yield runner


@pytest.fixture
def cli_runner():
    """Fixture for Typer CLI testing."""
    return CliRunner(mix_stderr=True)


@pytest.fixture
def html_file(tmp_path):
    """Fixture providing a temporary HTML file for testing."""
    html = tmp_path / "test.html"
    html.write_text("<html><head></head><body>content</body></html>")
    return html


class TestTestRunner:
    """Test the core TestRunner functionality."""

    def test_initialization(self):
        """Test TestRunner initializes correctly."""
        runner = TestRunner()
        assert runner.exit_status == 0

    def test_track_exit_code(self, mock_runner):
        """Test exit code tracking with bitwise OR."""
        mock_runner.track_exit_code(1)
        assert mock_runner.exit_status == 1

        mock_runner.track_exit_code(2)
        assert mock_runner.exit_status == 3  # 1 | 2 = 3

        mock_runner.track_exit_code(0)
        assert mock_runner.exit_status == 3  # No change on success

    def test_run_command_actual_subprocess(self):
        """Test run_command calls actual subprocess.call."""
        runner = TestRunner()
        with patch("subprocess.call", return_value=42) as mock_call:
            result = runner.run_command(["echo", "test"])
            assert result == 42
            mock_call.assert_called_once_with(["echo", "test"])

    @pytest.mark.parametrize(
        "marker,config_flag,extra_flags,expected",
        [
            (None, None, None, ["pytest", "--cache-clear", "--ignore=tests/support/"]),
            (
                "database",
                "--db=MEMORY",
                None,
                [
                    "pytest",
                    "--cache-clear",
                    "--ignore=tests/support/",
                    "-m",
                    "database",
                    "--db=MEMORY",
                ],
            ),
            (
                None,
                None,
                ["--verbose"],
                ["pytest", "--cache-clear", "--ignore=tests/support/", "--verbose"],
            ),
            (
                "broker",
                "--broker=REDIS",
                ["--slow"],
                [
                    "pytest",
                    "--cache-clear",
                    "--ignore=tests/support/",
                    "-m",
                    "broker",
                    "--broker=REDIS",
                    "--slow",
                ],
            ),
        ],
    )
    def test_build_test_command(
        self, mock_runner, marker, config_flag, extra_flags, expected
    ):
        """Test command building with various parameters."""
        result = mock_runner.build_test_command(marker, config_flag, extra_flags)
        assert result == expected

    def test_build_coverage_command(self, mock_runner):
        """Test coverage command wrapping."""
        pytest_cmd = ["pytest", "--version"]
        result = mock_runner.build_coverage_command(pytest_cmd)
        expected = ["coverage", "run", "--parallel-mode", "-m", "pytest", "--version"]
        assert result == expected

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (30.5, "30.50 seconds"),
            (75.2, "1m 15.2s (75.20 seconds)"),
            (3661.8, "61m 1.8s (3661.80 seconds)"),
        ],
    )
    def test_format_duration(self, mock_runner, seconds, expected):
        """Test duration formatting for various time periods."""
        assert mock_runner.format_duration(seconds) == expected

    def test_generate_test_suites(self, mock_runner):
        """Test test suite generation."""
        suites = mock_runner.generate_test_suites()

        assert (
            len(suites) == 8
        )  # Full Matrix + 3 DBs + 1 Brokers + 2 Manual Brokers + 1 EventStore
        suite_names = [suite.name for suite in suites]

        assert "Full Matrix" in suite_names
        assert all(f"Database: {db}" in suite_names for db in TEST_CONFIGS["databases"])
        assert all(
            f"Broker: {broker}" in suite_names for broker in TEST_CONFIGS["brokers"]
        )
        assert "Event Store: MESSAGE_DB" in suite_names

    def test_run_single_suite_success(self, mock_runner, capsys):
        """Test successful single suite execution."""
        suite = TestSuite("Test Suite", ["pytest", "--version"])

        result = mock_runner.run_single_suite(suite)
        assert result == 0

        captured = capsys.readouterr()
        assert "🚀 Starting tests for Test Suite..." in captured.out
        assert "✅ Completed tests for Test Suite" in captured.out

    def test_run_single_suite_failure(self, mock_runner, capsys):
        """Test failed single suite execution."""
        mock_runner.run_command = Mock(return_value=1)
        suite = TestSuite("Failing Suite", ["pytest", "--fail"])

        result = mock_runner.run_single_suite(suite)
        assert result == 1

        captured = capsys.readouterr()
        assert "❌ Failed tests for Failing Suite (exit code: 1)" in captured.out

    @pytest.mark.parametrize(
        "category,expected_configs",
        [
            ("DATABASE", TEST_CONFIGS["databases"]),
            ("BROKER", TEST_CONFIGS["brokers"]),
            ("EVENTSTORE", TEST_CONFIGS["eventstores"]),
        ],
    )
    def test_run_category_tests(self, mock_runner, category, expected_configs):
        """Test category-specific test execution."""
        result = mock_runner.run_category_tests(category)
        assert result == 0
        assert mock_runner.run_command.call_count == len(expected_configs)

    def test_run_category_tests_invalid_category(self, mock_runner):
        """Test run_category_tests with invalid category returns 0."""
        result = mock_runner.run_category_tests("INVALID_CATEGORY")
        assert result == 0
        assert mock_runner.run_command.call_count == 0

    def test_run_full_suite_parallel_default(self, mock_runner, capsys):
        """Test run_full_suite with default parallel execution."""
        mock_runner.run_test_suites_in_parallel = Mock(return_value=0)

        result = mock_runner.run_full_suite()  # sequential=False by default

        assert result == 0
        mock_runner.run_test_suites_in_parallel.assert_called_once()

    def test_run_full_suite_sequential_mode(self, mock_runner):
        """Test run_full_suite with sequential=True."""
        mock_runner.run_test_suites_sequentially = Mock(return_value=0)

        result = mock_runner.run_full_suite(sequential=True)

        assert result == 0
        mock_runner.run_test_suites_sequentially.assert_called_once()


class TestTestSuite:
    """Test the TestSuite dataclass."""

    def test_creation(self):
        """Test TestSuite creation."""
        suite = TestSuite("Test Name", ["command", "arg"])
        assert suite.name == "Test Name"
        assert suite.command == ["command", "arg"]


class TestCLICommands:
    """Test CLI command integration."""

    @pytest.mark.parametrize(
        "category", ["CORE", "DATABASE", "EVENTSTORE", "BROKER", "FULL", "COVERAGE"]
    )
    def test_all_categories_work(self, cli_runner, category):
        """Test all categories execute without errors."""
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_instance.run_category_tests.return_value = 0
            mock_instance.run_full_suite.return_value = 0
            mock_instance.run_command.return_value = 0
            mock_runner_class.return_value = mock_instance

            result = cli_runner.invoke(
                app, ["test", "--category", category], standalone_mode=False
            )
            assert result.exit_code == 0

    def test_sequential_flag(self, cli_runner):
        """Test sequential flag is passed correctly."""
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_instance.run_full_suite.return_value = 0
            mock_runner_class.return_value = mock_instance

            cli_runner.invoke(
                app,
                ["test", "--category", "FULL", "--sequential"],
                standalone_mode=False,
            )

            mock_instance.run_full_suite.assert_called_once_with(True)

    def test_coverage_with_diff_report(self, cli_runner):
        """Test coverage category generates diff report on success."""
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_instance.run_full_suite.return_value = 0
            mock_runner_class.return_value = mock_instance

            cli_runner.invoke(
                app, ["test", "--category", "COVERAGE"], standalone_mode=False
            )

            mock_instance.generate_diff_coverage_report.assert_called_once()

    def test_coverage_skips_diff_report_on_failure(self, cli_runner, capsys):
        """Test coverage category skips diff report when tests fail."""
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_instance.run_full_suite.return_value = 1
            mock_runner_class.return_value = mock_instance

            result = cli_runner.invoke(app, ["test", "--category", "COVERAGE"])

            assert result.exit_code == 1
            mock_instance.generate_diff_coverage_report.assert_not_called()

    def test_invalid_category_rejected(self, cli_runner):
        """Test invalid categories are rejected."""
        result = cli_runner.invoke(
            app, ["test", "--category", "INVALID"], standalone_mode=False
        )
        assert result.exit_code == 1
        assert "is not one of" in str(result.exception)


class TestSequentialExecution:
    """Test sequential execution functionality."""

    def test_sequential_execution_success(self, mock_runner, capsys):
        """Test successful sequential execution."""
        suites = [
            TestSuite("Full Matrix", ["echo", "test1"]),
            TestSuite("Database: MEMORY", ["echo", "test2"]),
        ]

        with patch("time.time", side_effect=[100.0, 105.0]):
            result = mock_runner.run_test_suites_sequentially(suites)

        assert result == 0
        captured = capsys.readouterr()
        assert "⏱️  Starting sequential test execution..." in captured.out
        assert "Running full test matrix..." in captured.out
        assert "Running tests for Database: MEMORY…" in captured.out


class TestParallelExecution:
    """Test parallel execution functionality."""

    def test_parallel_execution_success(self, mock_runner, capsys):
        """Test successful parallel execution."""
        suites = [
            TestSuite("Suite 1", ["echo", "test1"]),
            TestSuite("Suite 2", ["echo", "test2"]),
        ]

        with patch("time.time", side_effect=[100.0, 105.0]):
            result = mock_runner.run_test_suites_in_parallel(suites)

        assert result == 0
        captured = capsys.readouterr()
        assert "🔄 Running 2 test suites in parallel" in captured.out
        assert "📊 Progress:" in captured.out

    def test_parallel_execution_with_exception(self, mock_runner, capsys):
        """Test parallel execution handles exceptions."""
        suites = [TestSuite("Failing Suite", ["false"])]

        # Mock executor that raises exception
        class MockFuture:
            def result(self):
                raise RuntimeError("Test exception")

        class MockExecutor:
            def __init__(self, max_workers=3):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def submit(self, fn, suite, quiet=False):
                return MockFuture()

        with patch("protean.cli.test.ThreadPoolExecutor", MockExecutor), patch(
            "protean.cli.test.as_completed", lambda x: list(x.keys())
        ):
            result = mock_runner.run_test_suites_in_parallel(suites)

        assert result != 0
        captured = capsys.readouterr()
        assert "💥 Test suite 'Failing Suite' generated an exception" in captured.out


class TestStyleInjection:
    """Test HTML style injection functionality."""

    def test_inject_style_success(self, mock_runner, html_file):
        """Test successful style injection."""
        from protean.cli.test import STYLE_BLOCK

        mock_runner.inject_html_style(html_file)
        content = html_file.read_text()
        assert STYLE_BLOCK in content
        assert content.count(STYLE_BLOCK) == 1

    def test_inject_style_idempotent(self, mock_runner, html_file):
        """Test style injection is idempotent."""
        from protean.cli.test import STYLE_BLOCK

        mock_runner.inject_html_style(html_file)
        mock_runner.inject_html_style(html_file)

        content = html_file.read_text()
        assert content.count(STYLE_BLOCK) == 1

    def test_inject_style_no_head_tag(self, mock_runner, tmp_path):
        """Test injection when no </head> tag exists."""
        html_file = tmp_path / "no_head.html"
        html_file.write_text("<html><body>content</body></html>")
        original_content = html_file.read_text()

        mock_runner.inject_html_style(html_file)
        assert html_file.read_text() == original_content

    def test_inject_style_nonexistent_file(self, mock_runner):
        """Test injection with nonexistent file doesn't raise exception."""
        mock_runner.inject_html_style(Path("nonexistent.html"))  # Should not raise


class TestCoverageReporting:
    """Test coverage and diff report functionality."""

    def test_generate_diff_coverage_report_success(self, mock_runner):
        """Test successful diff coverage report generation."""
        with patch("webbrowser.open") as mock_browser, patch.object(
            mock_runner, "inject_html_style"
        ) as mock_inject:
            mock_runner.run_command = Mock(return_value=0)
            mock_runner.generate_diff_coverage_report()

            mock_inject.assert_called_once()
            mock_browser.assert_called_once()

    def test_generate_diff_coverage_report_success_with_real_paths(self):
        """Test successful diff coverage report with real path operations."""
        runner = TestRunner()

        with patch.object(runner, "run_command", return_value=0), patch.object(
            runner, "inject_html_style"
        ) as mock_inject, patch("webbrowser.open") as mock_browser, patch(
            "os.path.abspath", return_value="/tmp/test_report.html"
        ) as mock_abspath:
            runner.generate_diff_coverage_report()

            # Verify the complete success path is executed
            mock_inject.assert_called_once()
            mock_browser.assert_called_once_with("file:///tmp/test_report.html")
            mock_abspath.assert_called_once()

    def test_generate_diff_coverage_report_failure(self, mock_runner):
        """Test diff coverage report when diff-cover command fails."""
        with patch("webbrowser.open") as mock_browser, patch.object(
            mock_runner, "inject_html_style"
        ) as mock_inject:
            mock_runner.run_command = Mock(return_value=1)
            mock_runner.generate_diff_coverage_report()

            mock_inject.assert_not_called()
            mock_browser.assert_not_called()


class TestTimingAndFinalization:
    """Test timing and finalization functionality."""

    def test_finalize_coverage_success(self, capsys):
        """Test coverage finalization on success."""
        runner = TestRunner()
        runner.exit_status = 0

        # Mock the run_command method properly
        with patch.object(runner, "run_command", return_value=0) as mock_run:
            runner._finalize_coverage_and_timing(100.0)

        captured = capsys.readouterr()
        assert "🎯 All tests passed!" in captured.out
        assert "⏱️  Total execution time:" in captured.out
        assert mock_run.call_count == 3  # combine, xml, report

    def test_finalize_coverage_failure(self, capsys):
        """Test coverage finalization on failure."""
        runner = TestRunner()
        runner.exit_status = 1

        # Mock the run_command method properly
        with patch.object(runner, "run_command", return_value=0):
            runner._finalize_coverage_and_timing(100.0)

        captured = capsys.readouterr()
        assert "❌ Some tests failed – skipping coverage combine." in captured.out
        assert "⏱️  Total execution time:" in captured.out


class TestConfiguration:
    """Test configuration constants and data structures."""

    def test_test_configs_structure(self):
        """Test TEST_CONFIGS has expected structure."""
        assert "databases" in TEST_CONFIGS
        assert "brokers" in TEST_CONFIGS
        assert "manual_brokers" in TEST_CONFIGS
        assert "eventstores" in TEST_CONFIGS
        assert "full_matrix_flags" in TEST_CONFIGS

        assert len(TEST_CONFIGS["databases"]) == 3
        assert len(TEST_CONFIGS["brokers"]) == 1
        assert len(TEST_CONFIGS["manual_brokers"]) == 2
        assert len(TEST_CONFIGS["eventstores"]) == 2

    def test_run_category_enum(self):
        """Test RunCategory enum has all expected values."""
        expected_categories = {
            "CORE",
            "EVENTSTORE",
            "DATABASE",
            "BROKER",
            "MANUAL_BROKER",
            "COVERAGE",
            "FULL",
        }
        actual_categories = {category.value for category in RunCategory}
        assert actual_categories == expected_categories
