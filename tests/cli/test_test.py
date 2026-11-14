import json
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import typer
from typer.testing import CliRunner

from protean._deprecation import ProteanDeprecationWarning, RemovedInProtean020Warning
from protean.cli import app
from protean.cli.test import (
    CAPABILITY_MARKER_MAP,
    COVERAGE_BASE_CMD,
    EVENT_STORE_ADAPTERS,
    FULL_MATRIX_IN_MEMORY,
    FULL_MATRIX_SERVICES,
    GENERIC_TEST_DIR,
    PYTEST_BASE_CMD,
    TEST_CONFIGS,
    CapabilityResult,
    PortSuite,
    RunCategory,
    TestRunner,
    TestSuite,
    _adapter_config,
    _get_applicable_markers,
    _port_row_command,
    _print_conformance_report,
    _provider_has_capability_for_marker,
    _requested_capabilities,
    _run_pytest_for_marker,
    build_full_conformance_suites,
    load_adapter_manifest,
    validate_category,
    validate_workers,
)
from protean.cli.test import (
    test_adapter as cli_test_adapter,
)
from protean.port.broker import BrokerCapabilities
from protean.port.cache import CacheCapabilities
from protean.port.event_store import EventStoreCapabilities
from tests.conftest import SERVICE_KEYWORDS, _select_service_tests


@pytest.fixture
def mock_runner():
    """Fixture providing a TestRunner with mocked subprocess calls."""
    runner = TestRunner()
    with patch.object(runner, "run_command", return_value=0):
        yield runner


@pytest.fixture
def cli_runner():
    """Fixture for Typer CLI testing."""
    return CliRunner()


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

        # Broker capability mappings
        assert runner.broker_capabilities
        assert runner.capability_hierarchy
        assert runner.capability_markers

        # Database capability mappings
        assert runner.database_capabilities == {
            "MEMORY": "IN_MEMORY",
            "POSTGRESQL": "RELATIONAL_FULL",
            "POSTGRESQL_PSYCOPG2": "RELATIONAL_FULL",
            "SQLITE": "RELATIONAL",
            "MSSQL": "RELATIONAL_FULL",
            "MYSQL": "RELATIONAL_JSON",
            "MARIADB": "RELATIONAL_JSON",
            "ELASTICSEARCH": "DOCUMENT_STORE",
        }
        # Every database names a capability set that exists, so a typo in either
        # table cannot leave a leg with an empty marker expression.
        assert set(runner.database_capabilities.values()) <= set(
            runner.database_capability_markers
        )

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

        # The two full matrix suites, one per database, one per broker, one
        # per non-memory event store, and one per conformance pair in the
        # manifest. Every term is derived, so adding an adapter to TEST_CONFIGS
        # or a pair to the manifest that the generator does not pick up fails
        # here.
        event_stores = [s for s in TEST_CONFIGS["eventstores"] if s != "MEMORY"]
        pairs = {
            p
            for e in load_adapter_manifest().adapters
            if e.lane != "off"
            for p in e.conformance
        }
        assert pairs
        expected = (
            2
            + len(TEST_CONFIGS["databases"])
            + len(TEST_CONFIGS["brokers"])
            + len(event_stores)
            + len(pairs)
        )
        assert len(suites) == expected
        suite_names = [suite.name for suite in suites]

        assert suite_names[:2] == [FULL_MATRIX_IN_MEMORY, FULL_MATRIX_SERVICES]
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
        "category,expected_runs",
        [
            ("DATABASE", len(TEST_CONFIGS["databases"])),
            ("BROKER", len(TEST_CONFIGS["brokers"])),
            # A marker run per store, and a conformance run per store but memory.
            ("EVENTSTORE", 2 * len(TEST_CONFIGS["eventstores"]) - 1),
        ],
    )
    def test_run_category_tests(self, mock_runner, category, expected_runs):
        """Test category-specific test execution."""
        result = mock_runner.run_category_tests(category)
        assert result == 0
        assert mock_runner.run_command.call_count == expected_runs

    def test_run_category_tests_invalid_category(self, mock_runner):
        """Test run_category_tests with invalid category returns 0."""
        result = mock_runner.run_category_tests("INVALID_CATEGORY")
        assert result == 0
        assert mock_runner.run_command.call_count == 0

    def test_run_full_suite_parallel_default(self, mock_runner, capsys):
        """Test run_full_suite with default parallel execution (matrix-first)."""
        mock_runner.run_full_suite_with_matrix_first = Mock(return_value=0)

        result = mock_runner.run_full_suite()  # sequential=False by default

        assert result == 0
        mock_runner.run_full_suite_with_matrix_first.assert_called_once()

    def test_run_full_suite_sequential_mode(self, mock_runner):
        """Test run_full_suite with sequential=True."""
        mock_runner.run_test_suites_sequentially = Mock(return_value=0)

        result = mock_runner.run_full_suite(sequential=True, workers="4")

        assert result == 0
        mock_runner.run_test_suites_sequentially.assert_called_once()
        (suites,) = mock_runner.run_test_suites_sequentially.call_args.args
        in_memory = next(s for s in suites if s.name == FULL_MATRIX_IN_MEMORY)
        assert "-n" not in in_memory.command

    def test_run_full_suite_with_matrix_first(self, mock_runner, capsys):
        """Test run_full_suite_with_matrix_first runs matrix first, then parallel."""
        # Create test suites
        suites = [
            TestSuite(FULL_MATRIX_IN_MEMORY, ["echo", "matrix"]),
            TestSuite("Database: MEMORY", ["echo", "db1"]),
            TestSuite("Broker: REDIS", ["echo", "broker1"]),
        ]

        with patch("time.time", side_effect=[100.0, 105.0]):
            result = mock_runner.run_full_suite_with_matrix_first(suites)

        assert result == 0
        captured = capsys.readouterr()
        assert (
            "🎯 Running full test suite with matrix-first approach..." in captured.out
        )
        assert "🚀 Phase 1: Running full matrix test suite..." in captured.out
        assert (
            "🔄 Phase 2: Running 2 remaining test suites in parallel..." in captured.out
        )

    def test_matrix_first_reports_a_suite_that_crashes(self, mock_runner, capsys):
        suites = [TestSuite("Database: MEMORY", ["echo", "db1"])]
        mock_runner.run_single_suite = Mock(side_effect=RuntimeError("worker died"))

        result = mock_runner.run_full_suite_with_matrix_first(suites)

        assert result != 0
        captured = capsys.readouterr()
        assert (
            "💥 Test suite 'Database: MEMORY' generated an exception: worker died"
            in captured.out
        )


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

    def test_sequential_flag(self, cli_runner, monkeypatch):
        """Test sequential flag is passed correctly."""
        monkeypatch.delenv("PROTEAN_TEST_WORKERS", raising=False)
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_instance.run_full_suite.return_value = 0
            mock_runner_class.return_value = mock_instance

            cli_runner.invoke(
                app,
                ["test", "--category", "FULL", "--sequential"],
                standalone_mode=False,
            )

            mock_instance.run_full_suite.assert_called_once_with(True, "0")

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

    @pytest.mark.parametrize(
        "category", ["core", "database", "eventstore", "broker", "full", "coverage"]
    )
    def test_case_insensitive_categories(self, cli_runner, category):
        """Test that category validation is case insensitive."""
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_runner_class.return_value = mock_instance
            mock_instance.run_command.return_value = 0
            mock_instance.run_category_tests.return_value = 0
            mock_instance.run_full_suite.return_value = 0
            mock_instance.generate_diff_coverage_report.return_value = None

            result = cli_runner.invoke(
                app, ["test", "--category", category], standalone_mode=False
            )
            assert result.exit_code == 0

    @pytest.mark.parametrize(
        "category", ["Core", "DataBase", "EventStore", "Broker", "Full", "CoverAge"]
    )
    def test_mixed_case_categories(self, cli_runner, category):
        """Test that category validation works with mixed case."""
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_runner_class.return_value = mock_instance
            mock_instance.run_command.return_value = 0
            mock_instance.run_category_tests.return_value = 0
            mock_instance.run_full_suite.return_value = 0
            mock_instance.generate_diff_coverage_report.return_value = None

            result = cli_runner.invoke(
                app, ["test", "--category", category], standalone_mode=False
            )
            assert result.exit_code == 0

    def test_no_category_defaults_to_core(self, cli_runner):
        """Test that not specifying a category defaults to CORE behavior."""
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_runner_class.return_value = mock_instance
            mock_instance.run_command.return_value = 0

            result = cli_runner.invoke(app, ["test"], standalone_mode=False)

            assert result.exit_code == 0
            # Should call run_command for CORE tests, not run_category_tests
            mock_instance.run_command.assert_called_once()
            mock_instance.run_category_tests.assert_not_called()
            mock_instance.run_full_suite.assert_not_called()


class TestCategoryValidation:
    """Test the validate_category function directly."""

    def test_validate_category_none_returns_core(self):
        """Test that None input returns CORE."""
        result = validate_category(None)
        assert result == "CORE"

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("core", "CORE"),
            ("CORE", "CORE"),
            ("Core", "CORE"),
            ("database", "DATABASE"),
            ("DATABASE", "DATABASE"),
            ("DataBase", "DATABASE"),
            ("eventstore", "EVENTSTORE"),
            ("EVENTSTORE", "EVENTSTORE"),
            ("EventStore", "EVENTSTORE"),
            ("broker", "BROKER"),
            ("BROKER", "BROKER"),
            ("Broker", "BROKER"),
            ("full", "FULL"),
            ("FULL", "FULL"),
            ("Full", "FULL"),
            ("coverage", "COVERAGE"),
            ("COVERAGE", "COVERAGE"),
            ("Coverage", "COVERAGE"),
        ],
    )
    def test_validate_category_case_insensitive(self, input_value, expected):
        """Test that validate_category handles case insensitivity correctly."""
        result = validate_category(input_value)
        assert result == expected

    @pytest.mark.parametrize(
        "invalid_value", ["invalid", "INVALID", "Invalid", "xyz", "test", ""]
    )
    def test_validate_category_invalid_raises_bad_parameter(self, invalid_value):
        """Test that invalid categories raise typer.BadParameter."""
        with pytest.raises(typer.BadParameter) as exc_info:
            validate_category(invalid_value)

        assert "is not one of" in str(exc_info.value)
        assert (
            "['CORE', 'EVENTSTORE', 'DATABASE', 'BROKER', 'COVERAGE', 'FULL', 'PR']"
            in str(exc_info.value)
        )

    def test_validate_category_whitespace_handling(self):
        """Test that validate_category handles whitespace correctly."""
        # Leading/trailing whitespace should still work (typer usually handles this)
        result = validate_category("core")
        assert result == "CORE"


class TestSequentialExecution:
    """Test sequential execution functionality."""

    def test_sequential_execution_success(self, mock_runner, capsys):
        """Test successful sequential execution."""
        suites = [
            TestSuite(FULL_MATRIX_IN_MEMORY, ["echo", "test1"]),
            TestSuite("Database: MEMORY", ["echo", "test2"]),
        ]

        with patch("time.time", side_effect=[100.0, 105.0]):
            result = mock_runner.run_test_suites_sequentially(suites)

        assert result == 0
        captured = capsys.readouterr()
        assert "⏱️  Starting sequential test execution..." in captured.out
        assert f"Running tests for {FULL_MATRIX_IN_MEMORY}…" in captured.out
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

        with (
            patch("protean.cli.test.ThreadPoolExecutor", MockExecutor),
            patch("protean.cli.test.as_completed", lambda x: list(x.keys())),
        ):
            result = mock_runner.run_test_suites_in_parallel(suites)

        assert result != 0
        captured = capsys.readouterr()
        assert "💥 Test suite 'Failing Suite' generated an exception" in captured.out


class TestSharedDatabaseSuites:
    """Suites that share one database must not run at the same time."""

    def test_postgresql_suites_share_one_database(self):
        suites = {s.name: s for s in TestRunner().generate_test_suites()}

        assert suites["Database: POSTGRESQL"].shared_database == "postgresql"
        assert suites["Database: POSTGRESQL_PSYCOPG2"].shared_database == "postgresql"
        assert suites["Database: MYSQL"].shared_database is None
        assert suites["Database: MARIADB"].shared_database is None
        assert suites[FULL_MATRIX_IN_MEMORY].shared_database is None
        assert suites[FULL_MATRIX_SERVICES].shared_database is None

    @staticmethod
    def _track_overlap(runner):
        """Make ``run_command`` record the most commands running at once."""
        state = {"active": 0, "peak": 0}
        guard = threading.Lock()

        def run_command(cmd):
            with guard:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.2)
            with guard:
                state["active"] -= 1
            return 0

        runner.run_command = run_command
        return state

    def test_suites_sharing_a_database_run_one_at_a_time(self):
        runner = TestRunner()
        suites = [
            TestSuite("Database: A", ["a"], shared_database="postgresql"),
            TestSuite("Database: B", ["b"], shared_database="postgresql"),
        ]
        state = self._track_overlap(runner)

        result = runner.run_test_suites_in_parallel(suites)

        assert result == 0
        assert state["peak"] == 1

    def test_suites_without_a_shared_database_still_overlap(self):
        runner = TestRunner()
        suites = [
            TestSuite("Database: A", ["a"]),
            TestSuite("Database: B", ["b"]),
        ]
        # Each command waits until the other one is running too. If the suites
        # ran one at a time, the barrier would time out and the command fail.
        both_running = threading.Barrier(2, timeout=10)
        started = []

        def run_command(cmd):
            if cmd[0] not in ("a", "b"):  # coverage erase / combine / report
                return 0
            started.append(cmd[0])
            try:
                both_running.wait()
            except threading.BrokenBarrierError:
                return 1
            return 0

        runner.run_command = run_command

        result = runner.run_test_suites_in_parallel(suites)

        assert sorted(started) == ["a", "b"]
        assert result == 0

    def test_matrix_first_run_serializes_shared_database_suites(self):
        runner = TestRunner()
        suites = [
            TestSuite(FULL_MATRIX_SERVICES, ["matrix"]),
            TestSuite("Database: A", ["a"], shared_database="postgresql"),
            TestSuite("Database: B", ["b"], shared_database="postgresql"),
        ]
        state = self._track_overlap(runner)

        result = runner.run_full_suite_with_matrix_first(suites)

        assert result == 0
        assert state["peak"] == 1


class TestFullMatrixSplit:
    """FULL runs the tests that need no service apart from the ones that do."""

    @staticmethod
    def _suites(workers: str = "logical") -> dict[str, TestSuite]:
        return {s.name: s for s in TestRunner().generate_test_suites(workers)}

    @staticmethod
    def _option(cmd: list[str], name: str) -> str:
        # Look after ``pytest``, so coverage's own ``-m pytest`` is skipped.
        pytest_args = cmd[cmd.index("pytest") + 1 :]
        return pytest_args[pytest_args.index(name) + 1]

    def test_in_memory_suite_leaves_out_every_service_test(self):
        cmd = self._suites()[FULL_MATRIX_IN_MEMORY].command

        assert "--service-tests=none" in cmd

    def test_in_memory_suite_spreads_over_the_workers(self):
        cmd = self._suites("4")[FULL_MATRIX_IN_MEMORY].command

        assert self._option(cmd, "-n") == "4"
        assert self._option(cmd, "--dist") == "loadfile"

    def test_zero_workers_runs_the_in_memory_suite_in_one_process(self):
        cmd = self._suites("0")[FULL_MATRIX_IN_MEMORY].command

        assert "-n" not in cmd

    def test_services_suite_runs_only_service_tests_in_one_process(self):
        cmd = self._suites("4")[FULL_MATRIX_SERVICES].command

        assert "--service-tests=only" in cmd
        assert "-n" not in cmd

    @pytest.mark.parametrize("name", [FULL_MATRIX_IN_MEMORY, FULL_MATRIX_SERVICES])
    def test_both_suites_switch_on_every_matrix_flag_under_coverage(self, name):
        cmd = self._suites()[name].command

        assert cmd[: len(COVERAGE_BASE_CMD)] == COVERAGE_BASE_CMD
        for flag in TEST_CONFIGS["full_matrix_flags"]:
            assert flag in cmd
        assert cmd[-1] == "tests"

    def test_every_matrix_service_flag_is_a_service_keyword(self):
        flags = [f for f in TEST_CONFIGS["full_matrix_flags"] if f != "--slow"]

        assert flags
        for flag in flags:
            assert flag.removeprefix("--") in SERVICE_KEYWORDS

    @staticmethod
    def _select(choice: str, items: list[Mock]) -> tuple[list[Mock], list[Mock]]:
        config = Mock()
        config.getoption.return_value = choice
        deselected: list[Mock] = []
        config.hook.pytest_deselected.side_effect = lambda items: deselected.extend(
            items
        )
        _select_service_tests(config, items)
        return items, deselected

    @staticmethod
    def _items() -> list[Mock]:
        marked = Mock(keywords={"test_a": 1, "redis": 1})
        under_a_service_package = Mock(keywords={"test_b": 1, "mssql": 1})
        plain = Mock(keywords={"test_c": 1, "database": 1})
        return [marked, under_a_service_package, plain]

    def test_none_keeps_only_the_tests_that_need_no_service(self):
        marked, packaged, plain = self._items()

        kept, deselected = self._select("none", [marked, packaged, plain])

        assert kept == [plain]
        assert deselected == [marked, packaged]

    def test_only_keeps_only_the_tests_that_need_a_service(self):
        marked, packaged, plain = self._items()

        kept, deselected = self._select("only", [marked, packaged, plain])

        assert kept == [marked, packaged]
        assert deselected == [plain]

    def test_all_keeps_every_test(self):
        items = self._items()

        kept, deselected = self._select("all", list(items))

        assert kept == items
        assert deselected == []

    @pytest.mark.parametrize(("choice", "collected"), [("none", 0), ("only", 2)])
    def test_a_test_under_a_service_package_counts_as_a_service_test(
        self, choice, collected
    ):
        # This file's tests carry no ``mssql`` marker. They need MSSQL because
        # they sit under the ``mssql`` package.
        path = "tests/adapters/repository/sqlalchemy_repo/mssql/test_mssql_provider.py"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                f"--service-tests={choice}",
                "--mssql",
                path,
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
            check=False,
        )

        node_ids = [line for line in result.stdout.splitlines() if "::" in line]
        assert len(node_ids) == collected, result.stdout

    def test_matrix_suites_run_in_order_before_the_rest(self):
        runner = TestRunner()
        started: list[str] = []
        guard = threading.Lock()

        def run_command(cmd):
            with guard:
                started.append(cmd[0])
            return 0

        runner.run_command = run_command
        suites = [
            TestSuite("Database: A", ["a"]),
            TestSuite(FULL_MATRIX_SERVICES, ["services"]),
            TestSuite(FULL_MATRIX_IN_MEMORY, ["in-memory"]),
        ]

        result = runner.run_full_suite_with_matrix_first(suites)

        assert result == 0
        suite_commands = [c for c in started if c != "coverage"]
        assert suite_commands == ["services", "in-memory", "a"]

    def test_a_failing_matrix_suite_does_not_stop_the_others(self, capsys):
        runner = TestRunner()
        started: list[str] = []

        def run_command(cmd):
            started.append(cmd[0])
            return 1 if cmd[0] == "in-memory" else 0

        runner.run_command = run_command
        suites = [
            TestSuite(FULL_MATRIX_IN_MEMORY, ["in-memory"]),
            TestSuite(FULL_MATRIX_SERVICES, ["services"]),
            TestSuite("Database: A", ["a"]),
        ]

        result = runner.run_full_suite_with_matrix_first(suites)

        assert result != 0
        assert [c for c in started if c != "coverage"] == ["in-memory", "services", "a"]
        assert (
            f"⚠️  {FULL_MATRIX_IN_MEMORY} tests failed, but continuing"
            in capsys.readouterr().out
        )

    @pytest.mark.parametrize("category", ["FULL", "COVERAGE"])
    @pytest.mark.parametrize(
        ("args", "workers"),
        [([], "logical"), (["--workers", "3"], "3"), (["--sequential"], "0")],
    )
    def test_cli_passes_the_workers_to_the_full_suite(
        self, cli_runner, monkeypatch, category, args, workers
    ):
        monkeypatch.delenv("PROTEAN_TEST_WORKERS", raising=False)
        with patch("protean.cli.test.TestRunner") as mock_runner_class:
            mock_instance = Mock()
            mock_instance.run_full_suite.return_value = 0
            mock_runner_class.return_value = mock_instance

            cli_runner.invoke(
                app, ["test", "--category", category, *args], standalone_mode=False
            )

            mock_instance.run_full_suite.assert_called_once_with(
                args == ["--sequential"], workers
            )


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
        with (
            patch("webbrowser.open") as mock_browser,
            patch.object(mock_runner, "inject_html_style") as mock_inject,
        ):
            mock_runner.run_command = Mock(return_value=0)
            mock_runner.generate_diff_coverage_report()

            mock_inject.assert_called_once()
            mock_browser.assert_called_once()

    def test_generate_diff_coverage_report_success_with_real_paths(self):
        """Test successful diff coverage report with real path operations."""
        runner = TestRunner()

        with (
            patch.object(runner, "run_command", return_value=0),
            patch.object(runner, "inject_html_style") as mock_inject,
            patch("webbrowser.open") as mock_browser,
            patch(
                "os.path.abspath", return_value="/tmp/test_report.html"
            ) as mock_abspath,
        ):
            runner.generate_diff_coverage_report()

            # Verify the complete success path is executed
            mock_inject.assert_called_once()
            mock_browser.assert_called_once_with("file:///tmp/test_report.html")
            mock_abspath.assert_called_once()

    def test_generate_diff_coverage_report_failure(self, mock_runner):
        """Test diff coverage report when diff-cover command fails."""
        with (
            patch("webbrowser.open") as mock_browser,
            patch.object(mock_runner, "inject_html_style") as mock_inject,
        ):
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
        assert "eventstores" in TEST_CONFIGS
        assert "full_matrix_flags" in TEST_CONFIGS

        # Named, not counted: a count here goes stale the moment an adapter is
        # added, and says nothing about which ones are in the matrix.
        assert {"MEMORY", "POSTGRESQL", "SQLITE", "MSSQL", "MYSQL", "MARIADB"} <= set(
            TEST_CONFIGS["databases"]
        )
        assert {"INLINE", "REDIS", "REDIS_PUBSUB"} == set(TEST_CONFIGS["brokers"])
        assert {"MEMORY", "MESSAGE_DB"} == set(TEST_CONFIGS["eventstores"])

    def test_run_category_enum(self):
        """Test RunCategory enum has all expected values."""
        expected_categories = {
            "CORE",
            "EVENTSTORE",
            "DATABASE",
            "BROKER",
            "COVERAGE",
            "FULL",
            "PR",
        }
        actual_categories = {category.value for category in RunCategory}
        assert actual_categories == expected_categories

    def test_elasticsearch_in_databases(self):
        """Test that ELASTICSEARCH is included in the databases list."""
        assert "ELASTICSEARCH" in TEST_CONFIGS["databases"]


class TestDatabaseMarkerExpression:
    """Test database capability marker expression generation."""

    def test_memory_marker_expression(self):
        """Test Memory produces correct marker expression."""
        runner = TestRunner()
        expr = runner.get_database_marker_expression("MEMORY")
        assert expr == "basic_storage or raw_queries or transactional"

    def test_postgresql_marker_expression(self):
        """Test PostgreSQL produces correct marker expression (RELATIONAL_FULL)."""
        runner = TestRunner()
        expr = runner.get_database_marker_expression("POSTGRESQL")
        assert expr == (
            "atomic_transactions or basic_storage or native_array "
            "or native_json or raw_queries or schema_management or transactional"
        )

    def test_sqlite_marker_expression(self):
        """Test SQLite produces correct marker expression (RELATIONAL)."""
        runner = TestRunner()
        expr = runner.get_database_marker_expression("SQLITE")
        assert expr == (
            "atomic_transactions or basic_storage or raw_queries "
            "or schema_management or transactional"
        )

    def test_mssql_marker_expression(self):
        """Test MSSQL produces correct marker expression (RELATIONAL_FULL)."""
        runner = TestRunner()
        expr = runner.get_database_marker_expression("MSSQL")
        # Same as PostgreSQL — both are RELATIONAL_FULL
        assert expr == runner.get_database_marker_expression("POSTGRESQL")

    def test_elasticsearch_marker_expression(self):
        """Test Elasticsearch produces correct marker expression (DOCUMENT_STORE)."""
        runner = TestRunner()
        expr = runner.get_database_marker_expression("ELASTICSEARCH")
        assert expr == "basic_storage or schema_management"

    def test_unknown_database_returns_empty(self):
        """Test unknown database name returns empty string."""
        runner = TestRunner()
        assert runner.get_database_marker_expression("UNKNOWN_DB") == ""

    def test_markers_are_sorted_alphabetically(self):
        """Test that marker expressions are consistently sorted."""
        runner = TestRunner()
        for db in runner.database_capabilities:
            expr = runner.get_database_marker_expression(db)
            markers = expr.split(" or ")
            assert markers == sorted(markers)

    def test_all_configured_databases_have_expressions(self):
        """Test every database in TEST_CONFIGS produces a non-empty expression."""
        runner = TestRunner()
        for db in TEST_CONFIGS["databases"]:
            expr = runner.get_database_marker_expression(db)
            assert expr, f"Database {db} produced an empty marker expression"

    def test_relational_full_superset_of_relational(self):
        """Test RELATIONAL_FULL markers are a superset of RELATIONAL markers."""
        runner = TestRunner()
        relational = runner.database_capability_markers["RELATIONAL"]
        relational_full = runner.database_capability_markers["RELATIONAL_FULL"]
        assert relational.issubset(relational_full)

    def test_all_databases_include_basic_storage(self):
        """Test all capability sets include basic_storage marker."""
        runner = TestRunner()
        for capability_set, markers in runner.database_capability_markers.items():
            assert "basic_storage" in markers, (
                f"Capability set {capability_set} missing basic_storage"
            )


class TestDatabaseCategoryTests:
    """Test capability-based DATABASE category execution."""

    def test_database_category_uses_capability_markers(self, capsys):
        """Test DATABASE category uses capability-based marker expressions."""
        runner = TestRunner()
        commands_run = []

        def capture_command(cmd):
            commands_run.append(cmd)
            return 0

        runner.run_command = capture_command
        runner.run_category_tests("DATABASE")

        # Verify each database was tested with capability markers, not "database"
        assert len(commands_run) == len(TEST_CONFIGS["databases"])
        for cmd in commands_run:
            # Should use -m with capability markers, not "database"
            assert "-m" in cmd
            marker_idx = cmd.index("-m") + 1
            marker_expr = cmd[marker_idx]
            assert "database" not in marker_expr.split(" or ")
            assert "basic_storage" in marker_expr

    def test_database_category_prints_capability_info(self, capsys):
        """Test DATABASE category prints capability info for each database."""
        runner = TestRunner()
        runner.run_command = lambda cmd: 0
        runner.run_category_tests("DATABASE")

        captured = capsys.readouterr()
        assert "MEMORY (IN_MEMORY)" in captured.out
        assert "POSTGRESQL (RELATIONAL_FULL)" in captured.out
        assert "SQLITE (RELATIONAL)" in captured.out
        assert "MSSQL (RELATIONAL_FULL)" in captured.out
        assert "ELASTICSEARCH (DOCUMENT_STORE)" in captured.out

    def test_database_category_passes_db_flag(self):
        """Test DATABASE category passes --db flag for each database."""
        runner = TestRunner()
        commands_run = []

        def capture_command(cmd):
            commands_run.append(cmd)
            return 0

        runner.run_command = capture_command
        runner.run_category_tests("DATABASE")

        for i, db in enumerate(TEST_CONFIGS["databases"]):
            assert f"--db={db}" in commands_run[i]

    def test_database_category_tracks_failures(self):
        """Test DATABASE category tracks exit codes from failing runs."""
        runner = TestRunner()
        call_count = 0

        def fail_second(cmd):
            nonlocal call_count
            call_count += 1
            return 1 if call_count == 2 else 0

        runner.run_command = fail_second
        result = runner.run_category_tests("DATABASE")

        assert result != 0


class TestDatabaseTestSuiteGeneration:
    """Test capability-based database test suite generation."""

    @staticmethod
    def _find_pytest_marker(command: list[str]) -> str:
        """Extract the pytest -m marker expression from a coverage-wrapped command.

        Coverage commands look like:
            coverage run --parallel-mode -m pytest ... -m "marker expr" ...
        The first -m belongs to coverage (module flag), the second to pytest.
        """
        # Find the last -m flag, which is the pytest marker
        indices = [i for i, arg in enumerate(command) if arg == "-m"]
        assert len(indices) >= 2, (
            f"Expected at least 2 -m flags, got {indices} in {command}"
        )
        return command[indices[-1] + 1]

    def test_database_suites_use_capability_markers(self):
        """Test generated database suites use capability markers."""
        runner = TestRunner()
        suites = runner.generate_test_suites()

        db_suites = [s for s in suites if s.name.startswith("Database:")]
        assert len(db_suites) == len(TEST_CONFIGS["databases"])

        for suite in db_suites:
            marker_expr = self._find_pytest_marker(suite.command)
            # Should not be the old "database" marker
            assert marker_expr != "database"
            assert "basic_storage" in marker_expr

    def test_database_suites_include_db_flag(self):
        """Test generated database suites include --db flag."""
        runner = TestRunner()
        suites = runner.generate_test_suites()

        for db in TEST_CONFIGS["databases"]:
            db_suite = next(s for s in suites if s.name == f"Database: {db}")
            assert f"--db={db}" in db_suite.command

    def test_elasticsearch_suite_has_limited_markers(self):
        """Test Elasticsearch suite only gets basic_storage and schema_management."""
        runner = TestRunner()
        suites = runner.generate_test_suites()

        es_suite = next(s for s in suites if s.name == "Database: ELASTICSEARCH")
        marker_expr = self._find_pytest_marker(es_suite.command)

        assert "basic_storage" in marker_expr
        assert "schema_management" in marker_expr
        # Should NOT include transaction or raw query markers
        assert "transactional" not in marker_expr
        assert "raw_queries" not in marker_expr

    def test_memory_suite_excludes_atomic_transactions(self):
        """Test Memory suite does not include atomic_transactions marker."""
        runner = TestRunner()
        suites = runner.generate_test_suites()

        mem_suite = next(s for s in suites if s.name == "Database: MEMORY")
        marker_expr = self._find_pytest_marker(mem_suite.command)

        assert "transactional" in marker_expr
        assert "atomic_transactions" not in marker_expr

    def test_database_suites_wrapped_in_coverage(self):
        """Test generated database suites are wrapped in coverage commands."""
        runner = TestRunner()
        suites = runner.generate_test_suites()

        db_suites = [s for s in suites if s.name.startswith("Database:")]
        for suite in db_suites:
            assert suite.command[:4] == [
                "coverage",
                "run",
                "--parallel-mode",
                "-m",
            ]


class TestDatabaseEmptyMarkerBranches:
    """Test branches where a database has no marker expression."""

    def test_generate_test_suites_skips_database_with_no_marker(self):
        """Database with empty marker expression is skipped in suite generation."""
        runner = TestRunner()
        original_dbs = TEST_CONFIGS["databases"]
        try:
            # Add an unknown database to the config list
            TEST_CONFIGS["databases"] = [*list(original_dbs), "UNKNOWN_DB"]

            suites = runner.generate_test_suites()
            suite_names = [s.name for s in suites]

            # UNKNOWN_DB should NOT produce a test suite (empty marker expr)
            assert "Database: UNKNOWN_DB" not in suite_names
            # All real databases should still have suites
            for db in original_dbs:
                assert f"Database: {db}" in suite_names
        finally:
            TEST_CONFIGS["databases"] = original_dbs

    def test_run_category_tests_skips_database_with_no_marker(self, capsys):
        """DATABASE category run skips databases with empty marker expression."""
        runner = TestRunner()
        commands_run = []

        def capture_command(cmd):
            commands_run.append(cmd)
            return 0

        runner.run_command = capture_command
        # Inject an unknown database into the config list
        original_dbs = TEST_CONFIGS["databases"]
        try:
            TEST_CONFIGS["databases"] = ["UNKNOWN_DB_X", *list(original_dbs)]
            runner.run_category_tests("DATABASE")
        finally:
            TEST_CONFIGS["databases"] = original_dbs

        # UNKNOWN_DB_X should not produce a command — only real databases
        for cmd in commands_run:
            assert "--db=UNKNOWN_DB_X" not in cmd
        assert len(commands_run) == len(original_dbs)


class TestCapabilityMarkerMap:
    """Test the CAPABILITY_MARKER_MAP constant."""

    def test_all_expected_markers_present(self):
        """Test that all capability markers are defined."""
        expected = {
            "basic_storage",
            "transactional",
            "atomic_transactions",
            "raw_queries",
            "schema_management",
            "native_json",
            "native_array",
        }
        assert set(CAPABILITY_MARKER_MAP.keys()) == expected

    def test_transactional_has_both_flags(self):
        """Test transactional maps to both real and simulated transaction flags."""
        assert "TRANSACTIONS" in CAPABILITY_MARKER_MAP["transactional"]
        assert "SIMULATED_TRANSACTIONS" in CAPABILITY_MARKER_MAP["transactional"]

    def test_basic_storage_has_four_flags(self):
        """Test basic_storage maps to the four foundation capabilities."""
        flags = CAPABILITY_MARKER_MAP["basic_storage"]
        assert set(flags) == {"CRUD", "FILTER", "BULK_OPERATIONS", "ORDERING"}


class TestProviderHasCapabilityForMarker:
    """Test _provider_has_capability_for_marker helper."""

    def test_memory_has_basic_storage(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        assert _provider_has_capability_for_marker(caps, "basic_storage") is True

    def test_memory_has_transactional(self):
        """Memory has SIMULATED_TRANSACTIONS which satisfies transactional."""
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        assert _provider_has_capability_for_marker(caps, "transactional") is True

    def test_memory_lacks_atomic_transactions(self):
        """Memory does not have real TRANSACTIONS."""
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        assert _provider_has_capability_for_marker(caps, "atomic_transactions") is False

    def test_memory_has_raw_queries(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        assert _provider_has_capability_for_marker(caps, "raw_queries") is True

    def test_memory_lacks_schema_management(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        assert _provider_has_capability_for_marker(caps, "schema_management") is False

    def test_relational_has_all_core_markers(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.RELATIONAL
        assert _provider_has_capability_for_marker(caps, "basic_storage") is True
        assert _provider_has_capability_for_marker(caps, "transactional") is True
        assert _provider_has_capability_for_marker(caps, "atomic_transactions") is True
        assert _provider_has_capability_for_marker(caps, "raw_queries") is True
        assert _provider_has_capability_for_marker(caps, "schema_management") is True

    def test_relational_lacks_native_json(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.RELATIONAL
        assert _provider_has_capability_for_marker(caps, "native_json") is False

    def test_relational_full_has_native_types(self):
        from protean.port.provider import DatabaseCapabilities

        caps = (
            DatabaseCapabilities.RELATIONAL
            | DatabaseCapabilities.NATIVE_JSON
            | DatabaseCapabilities.NATIVE_ARRAY
        )
        assert _provider_has_capability_for_marker(caps, "native_json") is True
        assert _provider_has_capability_for_marker(caps, "native_array") is True

    def test_document_store_has_basic_and_schema(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.DOCUMENT_STORE
        assert _provider_has_capability_for_marker(caps, "basic_storage") is True
        assert _provider_has_capability_for_marker(caps, "schema_management") is True

    def test_document_store_lacks_transactions(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.DOCUMENT_STORE
        assert _provider_has_capability_for_marker(caps, "transactional") is False
        assert _provider_has_capability_for_marker(caps, "atomic_transactions") is False

    def test_unknown_marker_returns_false(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        assert _provider_has_capability_for_marker(caps, "nonexistent_marker") is False


class TestGetApplicableMarkers:
    """Test _get_applicable_markers helper."""

    def test_memory_markers(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        run, skip = _get_applicable_markers(caps)
        assert "basic_storage" in run
        assert "transactional" in run
        assert "raw_queries" in run
        assert "atomic_transactions" in skip
        assert "schema_management" in skip
        assert "native_json" in skip
        assert "native_array" in skip

    def test_requested_capabilities_filter(self):
        """Only requested capabilities should appear in output."""
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        run, skip = _get_applicable_markers(caps, ["basic_storage", "native_json"])
        assert run == ["basic_storage"]
        assert skip == ["native_json"]

    def test_relational_all_core_markers(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.RELATIONAL
        run, skip = _get_applicable_markers(caps)
        assert "basic_storage" in run
        assert "transactional" in run
        assert "atomic_transactions" in run
        assert "raw_queries" in run
        assert "schema_management" in run
        assert "native_json" in skip
        assert "native_array" in skip

    def test_empty_requested_yields_no_markers(self):
        from protean.port.provider import DatabaseCapabilities

        caps = DatabaseCapabilities.IN_MEMORY
        run, skip = _get_applicable_markers(caps, [])
        assert run == []
        assert skip == []


class TestCapabilityResult:
    """Test CapabilityResult dataclass."""

    def test_default_values(self):
        result = CapabilityResult(name="test", status="PASS")
        assert result.name == "test"
        assert result.status == "PASS"
        assert result.passed == 0
        assert result.failed == 0
        assert result.errors == 0
        assert result.total == 0
        assert result.reason == ""

    def test_with_counts(self):
        result = CapabilityResult(
            name="basic_storage", status="PASS", passed=42, total=42
        )
        assert result.passed == 42
        assert result.total == 42


class TestRunPytestForMarker:
    """Test _run_pytest_for_marker with mocked subprocess."""

    def test_successful_run(self, tmp_path):
        """Test parsing a successful pytest run."""
        mock_output = "42 passed in 1.23s\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=mock_output, stderr="")
            result = _run_pytest_for_marker(
                marker="basic_storage",
                db_name="MEMORY",
                generic_test_dir=tmp_path,
            )

        assert result.status == "PASS"
        assert result.passed == 42
        assert result.total == 42

    def test_failed_run(self, tmp_path):
        """Test parsing a failed pytest run."""
        mock_output = "3 failed, 39 passed in 2.50s\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout=mock_output, stderr="")
            result = _run_pytest_for_marker(
                marker="basic_storage",
                db_name="MEMORY",
                generic_test_dir=tmp_path,
            )

        assert result.status == "FAIL"
        assert result.passed == 39
        assert result.failed == 3
        assert result.total == 42

    def test_no_tests_collected(self, tmp_path):
        """Test handling when no tests are collected (exit code 5)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=5, stdout="no tests ran\n", stderr=""
            )
            result = _run_pytest_for_marker(
                marker="native_json",
                db_name="MEMORY",
                generic_test_dir=tmp_path,
            )

        assert result.status == "SKIP"
        assert result.reason == "no tests collected"

    def test_verbose_mode_flag(self, tmp_path):
        """Test that verbose mode adds -v flag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            _run_pytest_for_marker(
                marker="basic_storage",
                db_name="MEMORY",
                generic_test_dir=tmp_path,
                verbose=True,
            )

            cmd = mock_run.call_args[0][0]
            assert "-v" in cmd
            assert "--tb=no" not in cmd

    def test_quiet_mode_flags(self, tmp_path):
        """Test that non-verbose mode adds --tb=no -q flags."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            _run_pytest_for_marker(
                marker="basic_storage",
                db_name="MEMORY",
                generic_test_dir=tmp_path,
                verbose=False,
            )

            cmd = mock_run.call_args[0][0]
            assert "--tb=no" in cmd
            assert "-q" in cmd
            assert "-v" not in cmd

    def test_db_flag_in_command(self, tmp_path):
        """Test that --db flag is passed to pytest."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            _run_pytest_for_marker(
                marker="basic_storage",
                db_name="POSTGRESQL",
                generic_test_dir=tmp_path,
            )

            cmd = mock_run.call_args[0][0]
            assert "--db=POSTGRESQL" in cmd

    def test_marker_in_command(self, tmp_path):
        """Test that -m marker is passed to pytest."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            _run_pytest_for_marker(
                marker="schema_management",
                db_name="MEMORY",
                generic_test_dir=tmp_path,
            )

            cmd = mock_run.call_args[0][0]
            # Command is: python -m pytest ... -m schema_management ...
            # The first -m is the Python module flag, the last is the pytest marker
            m_indices = [i for i, arg in enumerate(cmd) if arg == "-m"]
            assert len(m_indices) >= 2  # python -m pytest ... -m marker
            last_m_idx = m_indices[-1]
            assert cmd[last_m_idx + 1] == "schema_management"

    def test_errors_in_output(self, tmp_path):
        """Test parsing errors from pytest output."""
        mock_output = "2 errors, 1 failed, 5 passed in 1.00s\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout=mock_output, stderr="")
            result = _run_pytest_for_marker(
                marker="basic_storage",
                db_name="MEMORY",
                generic_test_dir=tmp_path,
            )

        assert result.status == "FAIL"
        assert result.passed == 5
        assert result.failed == 1
        assert result.errors == 2
        assert result.total == 8


class TestPrintConformanceReport:
    """Test _print_conformance_report output formatting."""

    def test_report_output_with_all_pass(self, capsys):
        """Test report with all capabilities passing."""
        results = [
            CapabilityResult("basic_storage", "PASS", passed=42, total=42),
            CapabilityResult("raw_queries", "PASS", passed=5, total=5),
        ]
        _print_conformance_report("memory", "MemoryProvider", results, ["native_json"])

        captured = capsys.readouterr()
        assert "Conformance Report: memory" in captured.out
        assert "basic_storage" in captured.out
        assert "PASS" in captured.out
        assert "42/42" in captured.out
        assert "native_json" in captured.out
        assert "SKIP" in captured.out
        assert "(not declared)" in captured.out
        assert "47 passed" in captured.out
        assert "0 failed" in captured.out

    def test_report_output_with_failures(self, capsys):
        """Test report with failing capabilities."""
        results = [
            CapabilityResult("basic_storage", "FAIL", passed=39, failed=3, total=42),
        ]
        _print_conformance_report("test", "TestProvider", results, [])

        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "39/42" in captured.out
        assert "3 failed" in captured.out

    def test_report_output_with_errors(self, capsys):
        """Test report shows errors in parenthetical."""
        results = [
            CapabilityResult(
                "basic_storage", "FAIL", passed=38, failed=2, errors=2, total=42
            ),
        ]
        _print_conformance_report("test", "TestProvider", results, [])

        captured = capsys.readouterr()
        assert "2 errors" in captured.out

    def test_report_output_with_skipped_capabilities(self, capsys):
        """Test report shows skipped capabilities."""
        results = []
        skipped = ["atomic_transactions", "schema_management", "native_json"]
        _print_conformance_report("memory", "MemoryProvider", results, skipped)

        captured = capsys.readouterr()
        assert "3 capabilities skipped" in captured.out
        for marker in skipped:
            assert marker in captured.out


@pytest.mark.no_test_domain
class TestTestAdapterCommand:
    """Tests for the test_adapter CLI function.

    Uses the real memory provider (fast, no external services).
    Exercises the full command path including real subprocess pytest runs.

    When called directly (not via Typer CLI), ``typer.Exit`` is raised
    directly, not ``SystemExit``.
    """

    def test_success_with_single_capability(self, capsys):
        """Run conformance against memory for a single capability."""
        # On success, the function returns normally (no exit raised)
        cli_test_adapter(provider="memory", capabilities="CRUD")

        captured = capsys.readouterr()
        assert "Conformance Report" in captured.out
        assert "basic_storage" in captured.out

    def test_unknown_provider_exits(self, capsys):
        """Unknown provider name exits with code 1."""
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(provider="nonexistent_provider_xyz")
        assert exc_info.value.exit_code == 1

        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_provider_setup_failure_exits(self, capsys):
        with (
            patch(
                "protean.domain.Domain._initialize",
                side_effect=RuntimeError("cannot connect"),
            ),
            pytest.raises(typer.Exit) as exc_info,
        ):
            cli_test_adapter(provider="memory")
        assert exc_info.value.exit_code == 1

        captured = capsys.readouterr()
        assert "Error initializing provider 'memory': cannot connect" in captured.out

    def test_invalid_capability_exits(self, capsys):
        """Unknown capability name exits with code 1."""
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(provider="memory", capabilities="nonexistent_cap")
        assert exc_info.value.exit_code == 1

        captured = capsys.readouterr()
        assert "Capability 'nonexistent_cap' is unknown" in captured.out

    def test_nonexistent_test_dir_exits(self, capsys):
        """Missing test directory exits with code 1."""
        with (
            pytest.warns(RemovedInProtean020Warning, match="--test-dir"),
            pytest.raises(typer.Exit) as exc_info,
        ):
            cli_test_adapter(provider="memory", test_dir="/nonexistent/path")
        assert exc_info.value.exit_code == 1

        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_no_applicable_capabilities(self, capsys):
        """Requested capability not declared by provider exits cleanly."""
        # Memory doesn't have native_json
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(provider="memory", capabilities="NATIVE_JSON")
        assert exc_info.value.exit_code == 0

        captured = capsys.readouterr()
        assert "No applicable capabilities" in captured.out

    def test_verbose_flag(self, capsys):
        """Verbose flag prints per-marker progress."""
        cli_test_adapter(
            provider="memory",
            capabilities="CRUD",
            verbose=True,
        )

        captured = capsys.readouterr()
        assert "Testing capability: basic_storage" in captured.out

    def test_skipped_capabilities_in_report(self, capsys):
        """Report includes skipped capabilities in output."""
        cli_test_adapter(provider="memory", capabilities="CRUD")

        captured = capsys.readouterr()
        assert "Conformance Report" in captured.out


def _report_rows(output: str) -> list[tuple[str, str, str]]:
    """Return the (capability, status, detail) rows of a conformance report."""
    lines = output.split("Conformance Report", 1)[1].splitlines()
    rules = [i for i, line in enumerate(lines) if line.startswith("-" * 56)]
    rows = []
    for line in lines[rules[0] + 1 : rules[1]]:
        name, status, *detail = line.split(maxsplit=2)
        rows.append((name, status, detail[0] if detail else ""))
    return rows


def _pytest_calls(mock_run: Mock) -> list[list[str]]:
    return [call.args[0] for call in mock_run.call_args_list]


def _option(cmd: list[str], name: str) -> str:
    return cmd[cmd.index(name) + 1]


@pytest.mark.no_test_domain
class TestPortConformance:
    """`test-adapter --port` runs a port's suite under tests/conformance/.

    Uses the real memory and inline adapters and real subprocess pytest runs
    against the placeholder suites.
    """

    @pytest.mark.parametrize(
        "port, provider, flag_class, not_declared",
        [
            (
                "event_store",
                "memory",
                EventStoreCapabilities,
                ["CONSUMER_GROUPS", "DURABLE", "SCHEMA_MANAGEMENT"],
            ),
            ("cache", "memory", CacheCapabilities, ["SHARED", "DURABLE"]),
            (
                "broker",
                "inline",
                BrokerCapabilities,
                ["MESSAGE_ORDERING", "BLOCKING_READ", "REPLAY", "STREAM_PARTITIONING"],
            ),
        ],
    )
    def test_reports_unmarked_then_one_row_per_flag(
        self, capsys, port, provider, flag_class, not_declared
    ):
        cli_test_adapter(port=port, provider=provider)

        rows = _report_rows(capsys.readouterr().out)
        assert rows[0] == ("unmarked", "PASS", "1/1")
        # Declared flags in definition order, then the undeclared ones.
        flag_names = [flag.name for flag in flag_class]
        assert [name for name, _, _ in rows[1:]] == [
            name for name in flag_names if name not in not_declared
        ] + not_declared
        skipped = [name for name, status, detail in rows if detail == "(not declared)"]
        assert skipped == not_declared
        assert all(status == "SKIP" for name, status, _ in rows if name in skipped)
        # A declared flag with no gated test yet shows as not collected.
        declared_rows = [r for r in rows[1:] if r[0] not in skipped]
        assert declared_rows
        assert all(r[1:] == ("SKIP", "(no tests collected)") for r in declared_rows)

    def test_runs_one_pytest_call_per_declared_row(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            cli_test_adapter(port="cache", provider="memory")

        calls = _pytest_calls(mock_run)
        assert [_option(cmd, "--capability") for cmd in calls] == [
            "none",
            "KEY_VALUE",
            "TTL",
            "PATTERN_MATCH",
        ]
        cmd = calls[0]
        assert cmd[3].endswith(str(Path("tests", "conformance", "cache")))
        assert _option(cmd, "--port") == "cache"
        assert _option(cmd, "--adapter") == "memory"
        assert json.loads(_option(cmd, "--adapter-config")) == {"provider": "memory"}

    def test_the_pytest_call_gets_the_configuration_as_given(self):
        # The inline broker adds ``IS_ASYNC`` to the configuration it is
        # built with; that key must not reach the pytest call.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            cli_test_adapter(port="broker", provider="inline", config='{"TTL": 5}')

        calls = _pytest_calls(mock_run)
        assert calls
        for cmd in calls:
            assert json.loads(_option(cmd, "--adapter-config")) == {
                "TTL": 5,
                "provider": "inline",
            }

    @pytest.mark.parametrize("port", ["cache", "broker"])
    def test_an_adapter_without_a_default_uri_names_the_missing_key(self, capsys, port):
        # The redis adapters read ``URI`` before they connect, so no server
        # is needed.
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(port=port, provider="redis")
        assert exc_info.value.exit_code == 1

        assert (
            f"Error initializing {port} adapter 'redis': the configuration has no "
            "'URI' key. Set it with --uri or --config."
        ) in capsys.readouterr().out

    def test_the_adapter_is_built_from_the_given_configuration(self, capsys):
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(
                port="cache", provider="redis", config='{"URI": "notaurl"}'
            )
        assert exc_info.value.exit_code == 1

        out = capsys.readouterr().out
        assert "Error initializing cache adapter 'redis': Redis URL must specify" in out

    def test_default_port_prints_the_database_marker_rows(self, capsys):
        cli_test_adapter(provider="memory")

        rows = _report_rows(capsys.readouterr().out)
        assert sorted(name for name, _, _ in rows) == sorted(CAPABILITY_MARKER_MAP)
        assert "unmarked" not in [name for name, _, _ in rows]

    def test_unknown_port_exits_with_the_valid_ports(self, capsys):
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(port="nope", provider="memory")
        assert exc_info.value.exit_code == 1

        assert (
            "Unknown port 'nope'. Valid ports: broker, cache, database, event_store"
            in capsys.readouterr().out
        )

    def test_unknown_port_exits_1_through_the_cli(self, cli_runner):
        result = cli_runner.invoke(
            app, ["test", "test-adapter", "--port", "nope", "--provider", "memory"]
        )

        assert result.exit_code == 1
        assert "Valid ports: broker, cache, database, event_store" in result.output

    def test_unknown_adapter_exits_with_the_registry_message(self, capsys):
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(port="cache", provider="nope")
        assert exc_info.value.exit_code == 1

        assert "Error: Unknown cache 'nope'. Available: memory" in (
            capsys.readouterr().out
        )

    def test_adapter_setup_failure_exits(self, capsys):
        with (
            patch(
                "protean.domain.Domain._initialize",
                side_effect=RuntimeError("cannot connect"),
            ),
            pytest.raises(typer.Exit) as exc_info,
        ):
            cli_test_adapter(port="cache", provider="memory")
        assert exc_info.value.exit_code == 1

        assert "Error initializing cache adapter 'memory': cannot connect" in (
            capsys.readouterr().out
        )

    def test_adapter_setup_failure_closes_the_probe_domain(self):
        with (
            patch(
                "protean.domain.Domain._initialize",
                side_effect=RuntimeError("cannot connect"),
            ),
            patch("protean.domain.Domain.close") as close,
            pytest.raises(typer.Exit),
        ):
            cli_test_adapter(port="cache", provider="memory")
        close.assert_called_once_with()

    def test_the_probe_domain_closes_before_the_rows_run(self):
        calls: list[str] = []
        with (
            patch(
                "protean.domain.Domain.close",
                autospec=True,
                side_effect=lambda domain: calls.append("close"),
            ),
            patch(
                "protean.cli.test._run_port_rows",
                side_effect=lambda *args: calls.append("rows") or [],
            ),
        ):
            cli_test_adapter(port="cache", provider="memory")
        assert calls == ["close", "rows"]

    def test_requested_flags_restrict_the_rows(self, capsys):
        cli_test_adapter(
            port="event_store", provider="memory", capabilities="DURABLE,WRITE"
        )

        assert _report_rows(capsys.readouterr().out) == [
            ("WRITE", "SKIP", "(no tests collected)"),
            ("DURABLE", "SKIP", "(not declared)"),
        ]

    def test_a_named_set_stands_for_its_flags(self, capsys):
        cli_test_adapter(port="event_store", provider="memory", capabilities="BASIC")

        rows = _report_rows(capsys.readouterr().out)
        assert [name for name, _, _ in rows] == [
            "WRITE",
            "READ_STREAM",
            "READ_CATEGORY",
            "READ_ALL",
        ]

    def test_only_undeclared_flags_requested_exits_0(self, capsys):
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(
                port="event_store", provider="memory", capabilities="DURABLE"
            )
        assert exc_info.value.exit_code == 0

        out = capsys.readouterr().out
        assert "No applicable capabilities to test for adapter 'memory'." in out
        assert _report_rows(out) == [("DURABLE", "SKIP", "(not declared)")]

    def test_unknown_flag_exits_with_the_port_flags(self, capsys):
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(port="event_store", provider="memory", capabilities="NOPE")
        assert exc_info.value.exit_code == 1

        out = capsys.readouterr().out
        assert "Unknown capability 'NOPE'" in out
        assert "EXPECTED_VERSION" in out
        # A database flag is not a flag of the event store port.
        assert "CRUD" not in out

    def test_a_failing_row_exits_1(self, capsys):
        with (
            patch("subprocess.run") as mock_run,
            pytest.raises(typer.Exit) as exc_info,
        ):
            mock_run.return_value = Mock(returncode=1, stdout="1 failed\n", stderr="")
            cli_test_adapter(port="cache", provider="memory")
        assert exc_info.value.exit_code == 1

        rows = _report_rows(capsys.readouterr().out)
        assert rows[0] == ("unmarked", "FAIL", "0/1 (1 failed)")

    def test_verbose_prints_each_row(self, capsys):
        cli_test_adapter(
            port="cache", provider="memory", capabilities="TTL", verbose=True
        )

        assert "Testing capability: TTL" in capsys.readouterr().out

    def test_missing_suite_folder_needs_a_source_checkout(
        self, capsys, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("protean.cli.test.CONFORMANCE_DIR", tmp_path)

        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(port="cache", provider="memory")
        assert exc_info.value.exit_code == 1

        out = capsys.readouterr().out
        assert f"Conformance suite not found: {tmp_path / 'cache'}" in out
        assert "need a Protean source checkout" in out

    def test_missing_database_suite_needs_a_source_checkout(
        self, capsys, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("protean.cli.test.GENERIC_TEST_DIR", tmp_path / "generic")

        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(provider="memory")
        assert exc_info.value.exit_code == 1

        out = capsys.readouterr().out
        assert f"Generic test directory not found: {tmp_path / 'generic'}" in out
        assert "need a Protean source checkout" in out

    def test_missing_test_dir_gives_no_checkout_hint(self, capsys, tmp_path):
        with (
            pytest.warns(RemovedInProtean020Warning, match="--test-dir"),
            pytest.raises(typer.Exit) as exc_info,
        ):
            cli_test_adapter(provider="memory", test_dir=str(tmp_path / "x"))
        assert exc_info.value.exit_code == 1

        out = capsys.readouterr().out
        assert f"Generic test directory not found: {tmp_path / 'x'}" in out
        assert "source checkout" not in out

    def test_test_dir_is_rejected_for_other_ports(self, capsys):
        with (
            pytest.warns(RemovedInProtean020Warning, match="--test-dir"),
            pytest.raises(typer.Exit) as exc_info,
        ):
            cli_test_adapter(port="cache", provider="memory", test_dir="x")
        assert exc_info.value.exit_code == 1

        assert "--test-dir applies to --port database only" in (capsys.readouterr().out)


@pytest.mark.no_test_domain
class TestPortAdapterConfig:
    """`--uri` and `--config` reach the adapter configuration of the pytest call."""

    @pytest.mark.parametrize(
        "port, provider, uri, flags, key",
        [
            (
                "broker",
                "redis",
                "redis://localhost:6379/0",
                BrokerCapabilities.PUBLISH,
                "URI",
            ),
            (
                "event_store",
                "message_db",
                "postgresql://message_store@localhost:5433/message_store",
                EventStoreCapabilities.WRITE,
                "database_uri",
            ),
        ],
    )
    def test_uri_sets_the_port_key_on_the_pytest_call(
        self, port, provider, uri, flags, key
    ):
        # The capability read would connect to the service, so it is stubbed;
        # the pytest call is built from the real options.
        with (
            patch(
                "protean.cli.test._load_port_capabilities",
                return_value=(flags, "Adapter"),
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            cli_test_adapter(port=port, provider=provider, uri=uri)

        calls = _pytest_calls(mock_run)
        assert len(calls) == 2  # unmarked and the one declared flag
        for cmd in calls:
            assert _option(cmd, "--adapter") == provider
            assert json.loads(_option(cmd, "--adapter-config")) == {
                "provider": provider,
                key: uri,
            }

    @pytest.mark.parametrize(
        "port, key",
        [
            ("database", "database_uri"),
            ("event_store", "database_uri"),
            ("broker", "URI"),
            ("cache", "URI"),
        ],
    )
    def test_uri_key_per_port(self, port, key):
        assert _adapter_config(port, "x", "scheme://host", {}) == {
            "provider": "x",
            key: "scheme://host",
        }

    def test_uri_wins_over_the_same_key_in_config(self):
        config = _adapter_config("cache", "redis", "redis://b", {"URI": "redis://a"})
        assert config["URI"] == "redis://b"

    def test_provider_wins_over_provider_in_config(self):
        assert _adapter_config("cache", "memory", "", {"provider": "redis"}) == {
            "provider": "memory"
        }

    def test_no_uri_leaves_the_key_out(self):
        assert _adapter_config("broker", "inline", "", {}) == {"provider": "inline"}

    def test_config_merges_into_the_pytest_call(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="1 passed\n", stderr="")
            cli_test_adapter(
                port="cache",
                provider="memory",
                config='{"TTL": 60}',
                capabilities="TTL",
            )

        (cmd,) = _pytest_calls(mock_run)
        assert json.loads(_option(cmd, "--adapter-config")) == {
            "provider": "memory",
            "TTL": 60,
        }

    @pytest.mark.parametrize(
        "config, message",
        [
            ("{not json", "--config is not valid JSON"),
            ("[1, 2]", "--config must be a JSON object, got list"),
        ],
    )
    def test_config_that_is_not_a_json_object_exits(self, capsys, config, message):
        with pytest.raises(typer.Exit) as exc_info:
            cli_test_adapter(port="cache", provider="memory", config=config)
        assert exc_info.value.exit_code == 1

        assert message in capsys.readouterr().out

    def test_row_command_quiet_and_verbose(self, tmp_path):
        suite = PortSuite("cache", "memory", {"provider": "memory"}, tmp_path)

        quiet = _port_row_command(suite, "unmarked", verbose=False)
        verbose = _port_row_command(suite, "TTL", verbose=True)

        assert _option(quiet, "--capability") == "none"
        assert quiet[-2:] == ["--tb=no", "-q"]
        assert _option(verbose, "--capability") == "TTL"
        assert verbose[-1] == "-v"


@pytest.mark.no_test_domain
class TestDatabaseCapabilityNames:
    """`--port database` takes flag names; the old marker names warn."""

    def test_a_marker_name_warns_and_still_runs(self, capsys):
        with pytest.warns(RemovedInProtean020Warning, match=r"v0\.20\.0") as record:
            cli_test_adapter(
                port="database", provider="memory", capabilities="basic_storage"
            )

        (deprecation,) = [w for w in record if w.category is RemovedInProtean020Warning]
        assert "`basic_storage`" in str(deprecation.message)
        rows = _report_rows(capsys.readouterr().out)
        assert [(name, status) for name, status, _ in rows] == [
            ("basic_storage", "PASS")
        ]

    def test_a_flag_name_runs_without_a_warning(self, capsys):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cli_test_adapter(port="database", provider="memory", capabilities="CRUD")

        assert not [
            w for w in caught if issubclass(w.category, ProteanDeprecationWarning)
        ]
        rows = _report_rows(capsys.readouterr().out)
        assert [(name, status) for name, status, _ in rows] == [
            ("basic_storage", "PASS")
        ]

    def test_a_flag_selects_every_marker_whose_flags_include_it(self):
        assert _requested_capabilities("TRANSACTIONS") == [
            "transactional",
            "atomic_transactions",
        ]

    @pytest.mark.parametrize(
        "name, markers",
        [
            ("BASIC_STORAGE", ["basic_storage"]),
            ("DOCUMENT_STORE", ["basic_storage", "schema_management"]),
        ],
    )
    def test_a_named_set_selects_every_marker_of_its_flags(self, name, markers):
        assert _requested_capabilities(name) == markers

    def test_unknown_name_lists_the_flag_names(self, capsys):
        with pytest.raises(typer.Exit) as exc_info:
            _requested_capabilities("OPTIMISTIC")
        assert exc_info.value.exit_code == 1

        assert (
            "Capability 'OPTIMISTIC' is unknown. Valid capabilities: CRUD, FILTER, "
            "BULK_OPERATIONS, ORDERING, TRANSACTIONS, SIMULATED_TRANSACTIONS, "
            "RAW_QUERIES, SCHEMA_MANAGEMENT, NATIVE_JSON, NATIVE_ARRAY, or a "
            "named set of them"
        ) in capsys.readouterr().out

    def test_a_flag_no_marker_lists_exits(self, capsys):
        with pytest.raises(typer.Exit) as exc_info:
            _requested_capabilities("OPTIMISTIC_LOCKING")
        assert exc_info.value.exit_code == 1

        assert (
            "Capability 'OPTIMISTIC_LOCKING' selects no database conformance test."
        ) in capsys.readouterr().out

    def test_test_dir_warns_and_still_runs(self, capsys):
        with pytest.warns(RemovedInProtean020Warning, match="--test-dir"):
            cli_test_adapter(
                provider="memory",
                capabilities="RAW_QUERIES",
                test_dir=str(GENERIC_TEST_DIR),
            )

        rows = _report_rows(capsys.readouterr().out)
        assert [(name, status) for name, status, _ in rows] == [("raw_queries", "PASS")]


@pytest.mark.no_test_domain
class TestDeprecationWarningVisibility:
    """The real CLI prints the deprecation warnings of `test-adapter`.

    pytest installs its own warning filters, so these run a fresh interpreter.
    """

    SCRIPT = (
        "from protean.cli.test import _warn_deprecated_option; "
        "_warn_deprecated_option('test_adapter_test_dir', 'The option')"
    )

    def test_the_warning_prints_under_default_filters(self):
        result = subprocess.run(
            [sys.executable, "-c", self.SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        assert "RemovedInProtean020Warning: The option" in result.stderr
        assert "v0.20.0" in result.stderr

    def test_a_warning_filter_from_the_user_still_applies(self):
        result = subprocess.run(
            [sys.executable, "-W", "error::DeprecationWarning", "-c", self.SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1
        assert "Traceback" in result.stderr
        assert "RemovedInProtean020Warning: The option" in result.stderr


class TestFrameworkDevelopmentHelp:
    """`protean test` and `test-adapter` advertise themselves as framework tooling.

    Rich/Typer may inject ANSI escape codes, so strip them before matching.
    """

    @staticmethod
    def _strip_ansi(text: str) -> str:
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def test_test_help_marks_framework_development(self, cli_runner):
        """`protean test --help` labels the command as framework development.

        Anchored to the ``test`` callback's own description line (not just the
        phrase appearing anywhere on the page) so it fails if that specific
        docstring loses the marker — the ``test-adapter`` row carries the same
        phrase and would otherwise mask the regression.
        """
        import re

        result = cli_runner.invoke(app, ["test", "--help"])
        assert result.exit_code == 0
        output = self._strip_ansi(result.output)
        assert re.search(r"\[Framework development\] Run tests with", output)

    def test_test_adapter_short_help_marks_framework_development(self, cli_runner):
        """The test-adapter subcommand carries the framework-development marker.

        It surfaces in the ``protean test --help`` command list; invoking
        ``test test-adapter --help`` directly would first trigger the ``test``
        callback (which runs the suite), so the group listing is the seam.

        The marker must appear on the ``test-adapter`` row itself — asserting
        the two conditions independently is vacuous, since the ``test``
        callback docstring also renders ``[Framework development]``.
        """
        import re

        result = cli_runner.invoke(app, ["test", "--help"])
        assert result.exit_code == 0
        output = self._strip_ansi(result.output)
        assert re.search(r"test-adapter\s+\[Framework development\]", output)


@pytest.mark.no_test_domain
class TestCoreWorkers:
    """CORE runs on pytest-xdist; every other category stays in one process."""

    def test_core_command_spreads_over_workers_by_file(self):
        assert TestRunner().build_core_command("logical") == [
            *PYTEST_BASE_CMD,
            "-n",
            "logical",
            "--dist",
            "loadfile",
        ]

    def test_zero_workers_runs_in_one_process(self):
        assert TestRunner().build_core_command("0") == PYTEST_BASE_CMD

    def _invoke(self, cli_runner, args, env=None):
        with patch("protean.cli.test.TestRunner.run_command", return_value=0) as run:
            result = cli_runner.invoke(
                app, ["test", *args], env=env, standalone_mode=False
            )
        return result, run

    def test_core_defaults_to_logical_workers(self, cli_runner, monkeypatch):
        monkeypatch.delenv("PROTEAN_TEST_WORKERS", raising=False)
        result, run = self._invoke(cli_runner, [])
        assert result.exit_code == 0
        run.assert_called_once_with(
            [*PYTEST_BASE_CMD, "-n", "logical", "--dist", "loadfile"]
        )

    @pytest.mark.parametrize("flag", ["-n", "--workers"])
    def test_workers_option_sets_the_count(self, cli_runner, flag):
        result, run = self._invoke(cli_runner, [flag, "4"])
        assert result.exit_code == 0
        run.assert_called_once_with([*PYTEST_BASE_CMD, "-n", "4", "--dist", "loadfile"])

    def test_workers_zero_turns_parallelism_off(self, cli_runner):
        result, run = self._invoke(cli_runner, ["--workers", "0"])
        assert result.exit_code == 0
        run.assert_called_once_with(PYTEST_BASE_CMD)

    def test_sequential_runs_core_in_one_process(self, cli_runner):
        result, run = self._invoke(cli_runner, ["--sequential", "--workers", "4"])
        assert result.exit_code == 0
        run.assert_called_once_with(PYTEST_BASE_CMD)

    def test_env_var_sets_the_count(self, cli_runner):
        result, run = self._invoke(cli_runner, [], env={"PROTEAN_TEST_WORKERS": "0"})
        assert result.exit_code == 0
        run.assert_called_once_with(PYTEST_BASE_CMD)

    @pytest.mark.parametrize("value", ["AUTO", " logical ", "007"])
    def test_accepted_spellings_are_normalised(self, value):
        assert validate_workers(value) in ("auto", "logical", "7")

    @pytest.mark.parametrize("value", ["", "-1", "many", "2.5", "²", "٣"])
    def test_invalid_worker_count_is_rejected(self, value):
        with pytest.raises(typer.BadParameter, match="not a worker count"):
            validate_workers(value)

    @pytest.mark.parametrize("category", ["FULL", "COVERAGE"])
    def test_full_suites_never_get_workers(self, cli_runner, category):
        with (
            patch("protean.cli.test.TestRunner.run_command", return_value=0) as run,
            patch("protean.cli.test.TestRunner.generate_diff_coverage_report"),
        ):
            result = cli_runner.invoke(
                app,
                ["test", "-c", category, "--workers", "8", "--sequential"],
                standalone_mode=False,
            )
        assert result.exit_code == 0
        commands = [call.args[0] for call in run.call_args_list]
        assert commands
        assert not any("-n" in cmd or "--dist" in cmd for cmd in commands)

    def test_core_rejects_a_bad_worker_count(self, cli_runner):
        result, run = self._invoke(cli_runner, ["--workers", "many"])
        assert isinstance(result.exception, typer.BadParameter)
        assert "not a worker count" in str(result.exception)
        run.assert_not_called()

    @pytest.mark.parametrize(
        "category", ["FULL", "COVERAGE", "DATABASE", "BROKER", "EVENTSTORE"]
    )
    def test_other_categories_ignore_a_bad_worker_count(self, cli_runner, category):
        with patch("protean.cli.test.TestRunner.generate_diff_coverage_report"):
            result, _ = self._invoke(
                cli_runner,
                ["-c", category, "--sequential"],
                env={"PROTEAN_TEST_WORKERS": "many"},
            )
        assert result.exit_code == 0

    @pytest.mark.parametrize("category", ["DATABASE", "BROKER", "EVENTSTORE"])
    def test_category_suites_never_get_workers(self, cli_runner, category):
        result, run = self._invoke(cli_runner, ["-c", category, "--workers", "8"])
        assert result.exit_code == 0
        commands = [call.args[0] for call in run.call_args_list]
        assert commands
        assert not any("-n" in cmd or "--dist" in cmd for cmd in commands)


class TestConformanceRuns:
    """Which runs ``protean test`` builds for the port conformance suites."""

    MEMORY_SUITE = "Conformance: event_store/memory"

    def _invoke(self, args: list[str], return_value: int = 0):
        with (
            patch(
                "protean.cli.test.TestRunner.run_command", return_value=return_value
            ) as run,
            patch(
                "protean.cli.test.TestRunner.run_single_suite",
                autospec=True,
                side_effect=lambda runner, suite, quiet=False: (
                    names.append(suite.name) or runner.run_command(suite.command)
                ),
            ),
            patch("protean.cli.test.TestRunner.generate_diff_coverage_report"),
        ):
            names: list[str] = []
            result = CliRunner().invoke(app, ["test", *args])
        return result, names, [call.args[0] for call in run.call_args_list]

    def test_full_runs_the_message_db_conformance_suite_under_coverage(self):
        suites = {s.name: s for s in TestRunner().generate_test_suites()}
        suite = suites["Conformance: event_store/message_db"]
        assert suite.command[:4] == COVERAGE_BASE_CMD
        assert suite.command[-5:] == [
            "tests/conformance/event_store",
            "--port",
            "event_store",
            "--adapter",
            "message_db",
        ]
        # It and the event-store suite truncate the same store, so they never
        # run at the same time.
        assert suite.shared_database == "message_db"
        assert suites["Event Store: MESSAGE_DB"].shared_database == "message_db"
        assert suites["Event Store: MESSAGE_DB"].command == [
            *COVERAGE_BASE_CMD,
            *PYTEST_BASE_CMD,
            "-m",
            "eventstore",
            "--store=MESSAGE_DB",
        ]

    def test_full_skips_the_conformance_pairs_of_an_off_adapter(self, tmp_path):
        manifest = tmp_path / "adapters.toml"
        manifest.write_text(
            '[adapters.parked]\nlane = "off"\n'
            'conformance = ["event_store:message_db"]\n'
            '[adapters.live]\nlane = "touched"\n'
            'conformance = ["cache:redis"]\n'
        )
        with patch(
            "protean.cli.test.load_adapter_manifest",
            side_effect=lambda: load_adapter_manifest(manifest),
        ):
            suites = build_full_conformance_suites(TestRunner())
        assert [s.name for s in suites] == ["Conformance: cache/redis"]

    def test_full_runs_and_combines_the_conformance_suite(self):
        result, names, commands = self._invoke(["-c", "FULL"])
        assert result.exit_code == 0, result.output
        assert "Conformance: event_store/message_db" in names
        assert ["coverage", "combine"] in commands

    def test_eventstore_runs_the_conformance_suite_on_message_db(self):
        result, _, commands = self._invoke(["-c", "EVENTSTORE"])
        assert result.exit_code == 0, result.output
        assert [*PYTEST_BASE_CMD, "-m", "eventstore", "--store=MEMORY"] in commands
        assert [*PYTEST_BASE_CMD, "-m", "eventstore", "--store=MESSAGE_DB"] in commands
        assert [
            *PYTEST_BASE_CMD,
            "tests/conformance/event_store",
            "--port",
            "event_store",
            "--adapter",
            "message_db",
        ] in commands

    def test_eventstore_fails_when_the_conformance_suite_fails(self):
        runner = TestRunner()
        with patch.object(
            runner,
            "run_command",
            side_effect=lambda cmd: 1 if "--adapter" in cmd else 0,
        ):
            assert runner.run_category_tests("EVENTSTORE") == 1

    def test_eventstore_maps_its_stores_to_registry_names(self):
        assert EVENT_STORE_ADAPTERS == {"MEMORY": "memory", "MESSAGE_DB": "message_db"}
        assert set(EVENT_STORE_ADAPTERS) == set(TEST_CONFIGS["eventstores"])

    @pytest.mark.parametrize(
        "args",
        [
            [],
            ["-c", "PR"],
            ["-c", "PR", "--no-adapters"],
            ["-c", "PR", "--no-core", "-a", "message-db"],
            ["-c", "FULL"],
            ["-c", "COVERAGE"],
            ["-c", "EVENTSTORE"],
            ["-c", "DATABASE"],
            ["-c", "BROKER"],
        ],
    )
    def test_no_category_runs_the_memory_suite_a_second_time(self, args):
        result, names, commands = self._invoke(args)
        assert result.exit_code == 0, result.output
        assert commands
        assert self.MEMORY_SUITE not in names
        # A command that names a conformance folder runs it on one adapter,
        # and with no --adapter the plugin picks the port's default adapter.
        for command in commands:
            if any(arg.startswith("tests/conformance") for arg in command):
                assert "--adapter" in command, command
                adapter = command[command.index("--adapter") + 1]
                assert adapter not in ("memory", "inline"), command

    def test_the_core_command_names_no_path(self):
        command = TestRunner().build_core_command("logical")
        assert command == [*PYTEST_BASE_CMD, "-n", "logical", "--dist", "loadfile"]
        assert not any("conformance" in arg for arg in command)

    @staticmethod
    def _collected_ids(*paths: str) -> list[str]:
        """The test ids the core command's flags collect from ``paths``."""
        command = TestRunner().build_core_command("0")
        command.remove("--cache-clear")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                *command,
                "-p",
                "no:cacheprovider",
                "--collect-only",
                "-q",
                *paths,
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return [line for line in result.stdout.splitlines() if "::" in line]

    def test_core_collects_each_event_store_test_once(self):
        # The core command names no path, so pytest collects the testpaths.
        # Collecting the folder by name gives the full list to look for.
        suite = self._collected_ids("tests/conformance/event_store")
        assert suite
        core = self._collected_ids()
        for test_id in suite:
            assert core.count(test_id) == 1, test_id

    def test_core_fails_when_a_conformance_test_fails(self, tmp_path, monkeypatch):
        # The core command collects the working directory when it finds no
        # pytest configuration, so it runs this failing suite test.
        suite = tmp_path / "tests" / "conformance" / "event_store"
        suite.mkdir(parents=True)
        (suite / "test_fails.py").write_text("def test_fails():\n    assert False\n")
        (tmp_path / "tests" / "test_passes.py").write_text(
            "def test_passes():\n    pass\n"
        )
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["test", "--workers", "0"])
        assert result.exit_code == 1, result.output
