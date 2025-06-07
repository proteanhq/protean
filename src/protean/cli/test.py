import os
import subprocess
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import typer
from typing_extensions import Annotated

# Configuration constants
REPORT_PATH = Path("diff_coverage_report.html")
MAX_WORKERS = 3
COVERAGE_BASE_CMD = ["coverage", "run", "--parallel-mode", "-m"]
PYTEST_BASE_CMD = ["pytest", "--cache-clear", "--ignore=tests/support/"]

# HTML styling for coverage reports
STYLE_BLOCK = """
<!-- Injected by protean CLI -->
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600&display=swap" rel="stylesheet">
<style>
    body {{ font-family: "Source Sans Pro", sans-serif; margin: 20px; background-color: #f8f9fa; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
    th, td {{ padding: 12px 15px; border: 1px solid #dee2e6; text-align: left; }}
    th {{ background-color: #343a40; color: white; }}
    tr:nth-child(even) {{ background-color: #f2f2f2; }}
    .low-coverage {{ color: red; font-weight: bold; }}
    .high-coverage {{ color: green; font-weight: bold; }}
</style>
"""

TEST_CONFIGS = {
    "databases": ["MEMORY", "POSTGRESQL", "SQLITE"],
    "brokers": ["INLINE", "REDIS_PUBSUB"],
    "eventstores": ["MEMORY", "MESSAGE_DB"],
    "full_matrix_flags": [
        "--slow",
        "--sqlite",
        "--postgresql",
        "--elasticsearch",
        "--redis",
        "--message_db",
    ],
}


class RunCategory(str, Enum):
    CORE = "CORE"
    EVENTSTORE = "EVENTSTORE"
    DATABASE = "DATABASE"
    BROKER = "BROKER"
    COVERAGE = "COVERAGE"
    FULL = "FULL"


@dataclass
class TestSuite:
    __test__ = False  # Prevent pytest from collecting this as a test class
    name: str
    command: list[str]


@dataclass
class TestRunner:
    """Encapsulates test execution logic and state tracking."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self):
        self.exit_status = 0

    def run_command(self, cmd: list[str]) -> int:
        """Execute a command and return its exit code."""
        return subprocess.call(cmd)

    def track_exit_code(self, code: int) -> None:
        """Track the highest exit code encountered."""
        self.exit_status |= code

    def build_test_command(
        self, marker: str = None, config_flag: str = None, extra_flags: list[str] = None
    ) -> list[str]:
        """Build a pytest command with optional marker and configuration."""
        cmd = PYTEST_BASE_CMD.copy()
        if marker:
            cmd.extend(["-m", marker])
        if config_flag:
            cmd.append(config_flag)
        if extra_flags:
            cmd.extend(extra_flags)
        return cmd

    def build_coverage_command(self, pytest_cmd: list[str]) -> list[str]:
        """Build a coverage command wrapping pytest."""
        return COVERAGE_BASE_CMD + pytest_cmd

    def format_duration(self, seconds: float) -> str:
        """Format duration in a human-readable format."""
        minutes = int(seconds // 60)
        if minutes > 0:
            return f"{minutes}m {seconds % 60:.1f}s ({seconds:.2f} seconds)"
        return f"{seconds:.2f} seconds"

    def inject_html_style(self, path: Path) -> None:
        """Inject CSS styling into HTML report."""
        with suppress(FileNotFoundError):
            html = path.read_text(encoding="utf-8")
            if "</head>" in html and STYLE_BLOCK not in html:
                html = html.replace("</head>", f"{STYLE_BLOCK}\n</head>")
                path.write_text(html, encoding="utf-8")

    def generate_test_suites(self) -> list[TestSuite]:
        """Generate all test suites for comprehensive testing."""
        suites = []

        # Full matrix test
        full_cmd = self.build_coverage_command(
            self.build_test_command(
                extra_flags=TEST_CONFIGS["full_matrix_flags"] + ["tests"]
            )
        )
        suites.append(TestSuite("Full Matrix", full_cmd))

        # Database tests
        for db in TEST_CONFIGS["databases"]:
            cmd = self.build_coverage_command(
                self.build_test_command("database", f"--db={db}")
            )
            suites.append(TestSuite(f"Database: {db}", cmd))

        # Broker tests
        for broker in TEST_CONFIGS["brokers"]:
            cmd = self.build_coverage_command(
                self.build_test_command("broker", f"--broker={broker}")
            )
            suites.append(TestSuite(f"Broker: {broker}", cmd))

        # Eventstore tests
        for store in ["MESSAGE_DB"]:  # Only MESSAGE_DB for full suite
            cmd = self.build_coverage_command(
                self.build_test_command("eventstore", f"--store={store}")
            )
            suites.append(TestSuite(f"Event Store: {store}", cmd))

        return suites

    def run_single_suite(self, suite: TestSuite, quiet: bool = False) -> int:
        """Execute a single test suite."""
        print(f"🚀 Starting tests for {suite.name}...")

        cmd = suite.command
        if quiet:
            cmd = cmd + ["--tb=short", "-q"]

        result = self.run_command(cmd)
        status_icon = "✅" if result == 0 else "❌"
        print(
            f"{status_icon} {'Completed' if result == 0 else 'Failed'} tests for {suite.name}"
            + (f" (exit code: {result})" if result != 0 else "")
        )

        return result

    def run_test_suites_in_parallel(self, suites: list[TestSuite]) -> int:
        """Execute test suites in parallel."""
        start_time = time.time()
        print(
            f"🔄 Running {len(suites)} test suites in parallel (max {MAX_WORKERS} workers)..."
        )

        self.track_exit_code(self.run_command(["coverage", "erase"]))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_suite = {
                executor.submit(self.run_single_suite, suite, quiet=True): suite
                for suite in suites
            }

            for i, future in enumerate(as_completed(future_to_suite), 1):
                suite = future_to_suite[future]
                try:
                    result = future.result()
                    self.track_exit_code(result)
                    print(f"📊 Progress: {i}/{len(suites)} test suites completed")
                except Exception as exc:
                    print(f"💥 Test suite '{suite.name}' generated an exception: {exc}")
                    self.track_exit_code(1)

        self._finalize_coverage_and_timing(start_time)
        return self.exit_status

    def run_test_suites_sequentially(self, suites: list[TestSuite]) -> int:
        """Execute test suites sequentially."""
        start_time = time.time()
        print("⏱️  Starting sequential test execution...")

        self.track_exit_code(self.run_command(["coverage", "erase"]))

        for suite in suites:
            if suite.name == "Full Matrix":
                print("Running full test matrix...")
            else:
                print(f"Running tests for {suite.name}…")

            result = self.run_command(suite.command)
            self.track_exit_code(result)

        self._finalize_coverage_and_timing(start_time)
        return self.exit_status

    def _finalize_coverage_and_timing(self, start_time: float) -> None:
        """Finalize coverage processing and print timing information."""
        if self.exit_status == 0:
            print(
                "\n🎯 All tests passed! Combining coverage data and generating report..."
            )
            for cmd in [
                ["coverage", "combine"],
                ["coverage", "xml"],
                ["coverage", "report"],
            ]:
                self.track_exit_code(self.run_command(cmd))
        else:
            print("\n❌ Some tests failed – skipping coverage combine.")

        duration = time.time() - start_time
        print(f"\n⏱️  Total execution time: {self.format_duration(duration)}")

    def run_category_tests(self, category: str) -> int:
        """Run tests for a specific category."""
        config_map = {
            "EVENTSTORE": ("eventstore", TEST_CONFIGS["eventstores"], "--store"),
            "DATABASE": ("database", TEST_CONFIGS["databases"], "--db"),
            "BROKER": ("broker", TEST_CONFIGS["brokers"], "--broker"),
        }

        if category not in config_map:
            return 0

        marker, configs, flag_prefix = config_map[category]

        for config in configs:
            print(f"Running tests for {category}: {config}…")
            cmd = self.build_test_command(marker, f"{flag_prefix}={config}")
            self.track_exit_code(self.run_command(cmd))

        return self.exit_status

    def run_full_suite(self, sequential: bool = False) -> int:
        """Run the complete test suite with coverage."""
        suites = self.generate_test_suites()

        if sequential:
            return self.run_test_suites_sequentially(suites)
        else:
            return self.run_test_suites_in_parallel(suites)

    def generate_diff_coverage_report(self) -> None:
        """Generate and style the diff coverage report."""
        diff_cover_cmd = [
            "diff-cover",
            "coverage.xml",
            "--compare-branch=main",
            "--html-report",
            REPORT_PATH.name,
        ]

        if self.run_command(diff_cover_cmd) == 0:
            self.inject_html_style(REPORT_PATH)
            url = f"file://{os.path.abspath(REPORT_PATH.name)}"
            webbrowser.open(url)


app = typer.Typer()


@app.callback(invoke_without_command=True)
def test(
    category: Annotated[
        RunCategory, typer.Option("-c", "--category", case_sensitive=False)
    ] = RunCategory.CORE,
    sequential: Annotated[
        bool,
        typer.Option(
            "--sequential", help="Run tests sequentially instead of in parallel"
        ),
    ] = False,
):
    """Run tests with various configurations and coverage options."""
    runner = TestRunner()

    match category.value:
        case "EVENTSTORE" | "DATABASE" | "BROKER":
            exit_code = runner.run_category_tests(category.value)

        case "FULL":
            exit_code = runner.run_full_suite(sequential)

        case "COVERAGE":
            exit_code = runner.run_full_suite(sequential)
            if exit_code == 0:
                runner.generate_diff_coverage_report()
            else:
                print("\n❌ Tests failed – skipping diff-cover report.")

        case _:  # CORE
            print("Running core tests…")
            exit_code = runner.run_command(PYTEST_BASE_CMD)

    if exit_code != 0:
        raise typer.Exit(code=exit_code)
