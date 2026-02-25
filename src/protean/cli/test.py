import os
import subprocess
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from protean.port.provider import DatabaseCapabilities

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
    "databases": ["MEMORY", "POSTGRESQL", "SQLITE", "MSSQL", "ELASTICSEARCH"],
    "brokers": [
        "REDIS",
        "INLINE",
        "REDIS_PUBSUB",
    ],
    "eventstores": ["MEMORY", "MESSAGE_DB"],
    "full_matrix_flags": [
        "--slow",
        "--redis",
        "--sqlite",
        "--postgresql",
        "--message_db",
        "--elasticsearch",
        "--mssql",
    ],
}


class RunCategory(Enum):
    """Valid test run categories"""

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

        # Broker capability mappings
        self.broker_capabilities = {
            "INLINE": "RELIABLE_MESSAGING",
            "REDIS": "ORDERED_MESSAGING",
            "REDIS_PUBSUB": "SIMPLE_QUEUING",
        }

        # Capability hierarchy (from lowest to highest)
        self.capability_hierarchy = [
            "BASIC_PUBSUB",
            "SIMPLE_QUEUING",
            "RELIABLE_MESSAGING",
            "ORDERED_MESSAGING",
            "ENTERPRISE_STREAMING",
        ]

        # Capability to marker mapping
        self.capability_markers = {
            "BASIC_PUBSUB": "basic_pubsub",
            "SIMPLE_QUEUING": "simple_queuing",
            "RELIABLE_MESSAGING": "reliable_messaging",
            "ORDERED_MESSAGING": "ordered_messaging",
            "ENTERPRISE_STREAMING": "enterprise_streaming",
        }

        # Database capability mappings
        self.database_capabilities: dict[str, str] = {
            "MEMORY": "IN_MEMORY",
            "POSTGRESQL": "RELATIONAL_FULL",
            "SQLITE": "RELATIONAL",
            "MSSQL": "RELATIONAL_FULL",
            "ELASTICSEARCH": "DOCUMENT_STORE",
        }

        # Map convenience sets to applicable markers (set-based, not hierarchical)
        self.database_capability_markers: dict[str, set[str]] = {
            "IN_MEMORY": {"basic_storage", "transactional", "raw_queries"},
            "DOCUMENT_STORE": {"basic_storage", "schema_management"},
            "RELATIONAL": {
                "basic_storage",
                "transactional",
                "atomic_transactions",
                "raw_queries",
                "schema_management",
            },
            "RELATIONAL_FULL": {
                "basic_storage",
                "transactional",
                "atomic_transactions",
                "raw_queries",
                "schema_management",
                "native_json",
                "native_array",
            },
        }

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

    def get_capability_marker_expression(self, broker: str) -> str:
        """Get marker expression for broker's capabilities.

        Returns a marker expression like 'basic_pubsub or simple_queuing or reliable_messaging'
        that includes all capabilities up to and including the broker's level.
        """
        broker_capability = self.broker_capabilities.get(broker)
        if not broker_capability:
            return ""

        # Find the index of the broker's capability
        try:
            capability_index = self.capability_hierarchy.index(broker_capability)
        except ValueError:
            return ""

        # Get all capabilities up to and including the broker's level
        applicable_capabilities = self.capability_hierarchy[: capability_index + 1]

        # Convert to marker names and create OR expression
        marker_names = [self.capability_markers[cap] for cap in applicable_capabilities]

        return " or ".join(marker_names)

    def get_database_marker_expression(self, database: str) -> str:
        """Get marker expression for database's capabilities.

        Returns a marker expression like 'basic_storage or transactional or raw_queries'
        that includes all capability markers supported by this database.
        """
        capability = self.database_capabilities.get(database)
        if not capability:
            return ""
        markers = self.database_capability_markers.get(capability, set())
        return " or ".join(sorted(markers))

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

        # Database tests (capability-based)
        for db in TEST_CONFIGS["databases"]:
            marker_expression = self.get_database_marker_expression(db)
            if marker_expression:
                cmd = self.build_coverage_command(
                    self.build_test_command(
                        marker=marker_expression, extra_flags=[f"--db={db}"]
                    )
                )
                suites.append(TestSuite(f"Database: {db}", cmd))

        # Capability-based broker tests
        all_brokers = TEST_CONFIGS["brokers"]
        for broker in all_brokers:
            # Get marker expression for this broker's capabilities
            marker_expression = self.get_capability_marker_expression(broker)

            if marker_expression:
                # Use marker-based selection for broker tests
                cmd = self.build_coverage_command(
                    self.build_test_command(
                        marker=marker_expression, extra_flags=[f"--broker={broker}"]
                    )
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

        print(f"Running command: {' '.join(cmd)}")
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
        if category == "EVENTSTORE":
            for store in TEST_CONFIGS["eventstores"]:
                print(f"Running tests for EVENTSTORE: {store}…")
                cmd = self.build_test_command("eventstore", f"--store={store}")
                self.track_exit_code(self.run_command(cmd))
        elif category == "DATABASE":
            for db in TEST_CONFIGS["databases"]:
                marker_expression = self.get_database_marker_expression(db)
                if marker_expression:
                    db_capability = self.database_capabilities.get(db, "UNKNOWN")
                    print(f"Running tests for DATABASE: {db} ({db_capability})…")
                    cmd = self.build_test_command(
                        marker=marker_expression,
                        extra_flags=[f"--db={db}"],
                    )
                    self.track_exit_code(self.run_command(cmd))
        elif category == "BROKER":
            # Use capability-based testing for brokers
            all_brokers = TEST_CONFIGS["brokers"]
            for broker in all_brokers:
                marker_expression = self.get_capability_marker_expression(broker)

                if marker_expression:
                    broker_capability = self.broker_capabilities.get(broker, "UNKNOWN")
                    print(f"Running tests for BROKER: {broker} ({broker_capability})…")

                    # Use marker-based selection for broker tests
                    cmd = self.build_test_command(
                        marker=marker_expression, extra_flags=[f"--broker={broker}"]
                    )
                    self.track_exit_code(self.run_command(cmd))

        return self.exit_status

    def run_full_suite_with_matrix_first(self, suites: list[TestSuite]) -> int:
        """Run full matrix test first, then remaining suites in parallel."""
        start_time = time.time()
        print("🎯 Running full test suite with matrix-first approach...")

        self.track_exit_code(self.run_command(["coverage", "erase"]))

        # Find and run the full matrix test suite first
        full_matrix_suite = None
        remaining_suites = []

        for suite in suites:
            if suite.name == "Full Matrix":
                full_matrix_suite = suite
            else:
                remaining_suites.append(suite)

        if full_matrix_suite:
            print("🚀 Phase 1: Running full matrix test suite...")
            result = self.run_single_suite(full_matrix_suite)
            self.track_exit_code(result)

            # If full matrix fails, we might still want to run other suites
            # but let's track the failure
            if result != 0:
                print(
                    "⚠️  Full matrix tests failed, but continuing with remaining suites..."
                )

        # Run remaining suites in parallel
        if remaining_suites:
            print(
                f"\n🔄 Phase 2: Running {len(remaining_suites)} remaining test suites in parallel..."
            )

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_suite = {
                    executor.submit(self.run_single_suite, suite, quiet=True): suite
                    for suite in remaining_suites
                }

                for i, future in enumerate(as_completed(future_to_suite), 1):
                    suite = future_to_suite[future]
                    try:
                        result = future.result()
                        self.track_exit_code(result)
                        print(
                            f"📊 Progress: {i}/{len(remaining_suites)} remaining test suites completed"
                        )
                    except Exception as exc:
                        print(
                            f"💥 Test suite '{suite.name}' generated an exception: {exc}"
                        )
                        self.track_exit_code(1)

        self._finalize_coverage_and_timing(start_time)
        return self.exit_status

    def run_full_suite(self, sequential: bool = False) -> int:
        """Run the complete test suite with coverage.

        By default, runs the full matrix test suite first, then runs
        the remaining suites in parallel. With sequential=True, runs
        all suites sequentially.
        """
        suites = self.generate_test_suites()

        if sequential:
            return self.run_test_suites_sequentially(suites)
        else:
            return self.run_full_suite_with_matrix_first(suites)

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


def validate_category(value: str) -> str:
    """Validate and convert category string, returning the uppercase version."""
    if value is None:
        return "CORE"

    try:
        # Validate that the uppercase version is a valid RunCategory
        RunCategory(value.upper())
        return value.upper()
    except ValueError:
        valid_categories = [cat.value for cat in RunCategory]
        raise typer.BadParameter(f"'{value}' is not one of {valid_categories}")


@app.callback(invoke_without_command=True)
def test(
    category: Annotated[
        str,
        typer.Option(
            "-c",
            "--category",
            help="Test category to run",
            callback=validate_category,
        ),
    ] = "CORE",
    sequential: Annotated[
        bool,
        typer.Option(
            "--sequential", help="Run tests sequentially instead of in parallel"
        ),
    ] = False,
):
    """Run tests with various configurations and coverage options."""
    runner = TestRunner()

    match category:
        case "EVENTSTORE" | "DATABASE" | "BROKER":
            exit_code = runner.run_category_tests(category)

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


# --- Capability-to-marker mapping for test-adapter ---

# Maps individual DatabaseCapabilities flags to pytest marker names.
# This is the single source of truth for which capability flag corresponds
# to which marker.  The `transactional` marker is special: it accepts
# either TRANSACTIONS or SIMULATED_TRANSACTIONS.
CAPABILITY_MARKER_MAP: dict[str, list[str]] = {
    "basic_storage": ["CRUD", "FILTER", "BULK_OPERATIONS", "ORDERING"],
    "transactional": ["TRANSACTIONS", "SIMULATED_TRANSACTIONS"],
    "atomic_transactions": ["TRANSACTIONS"],
    "raw_queries": ["RAW_QUERIES"],
    "schema_management": ["SCHEMA_MANAGEMENT"],
    "native_json": ["NATIVE_JSON"],
    "native_array": ["NATIVE_ARRAY"],
}

# Path to the generic test directory relative to the protean package
GENERIC_TEST_DIR = Path(__file__).resolve().parent.parent.parent.parent / (
    "tests/adapters/repository/generic"
)


@dataclass
class CapabilityResult:
    """Result of running tests for a single capability."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    name: str
    status: str  # "PASS", "FAIL", "SKIP"
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    reason: str = ""


def _provider_has_capability_for_marker(
    provider_capabilities: "DatabaseCapabilities", marker_name: str
) -> bool:
    """Check whether a provider's capabilities satisfy a given marker.

    For ``transactional``, the provider needs TRANSACTIONS or SIMULATED_TRANSACTIONS.
    For all other markers, ALL listed capability flags must be present.
    """
    from protean.port.provider import DatabaseCapabilities

    flag_names = CAPABILITY_MARKER_MAP.get(marker_name, [])
    if not flag_names:
        return False

    if marker_name == "transactional":
        # Any of the listed flags is sufficient
        return any(DatabaseCapabilities[f] in provider_capabilities for f in flag_names)
    else:
        # All listed flags must be present
        return all(DatabaseCapabilities[f] in provider_capabilities for f in flag_names)


def _get_applicable_markers(
    provider_capabilities: "DatabaseCapabilities",
    requested_capabilities: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Determine which markers to run and which to skip.

    Returns:
        A tuple of (markers_to_run, markers_to_skip).
    """
    all_markers = list(CAPABILITY_MARKER_MAP.keys())

    if requested_capabilities is not None:
        # Only consider requested capabilities
        all_markers = [m for m in all_markers if m in requested_capabilities]

    markers_to_run = []
    markers_to_skip = []

    for marker in all_markers:
        if _provider_has_capability_for_marker(provider_capabilities, marker):
            markers_to_run.append(marker)
        else:
            markers_to_skip.append(marker)

    return markers_to_run, markers_to_skip


def _run_pytest_for_marker(
    marker: str,
    db_name: str,
    generic_test_dir: Path,
    verbose: bool = False,
) -> CapabilityResult:
    """Run pytest for a single capability marker and parse results.

    Uses ``--tb=no -q`` by default for clean output, or ``-v`` in verbose mode.
    Results are captured via pytest's JSON report plugin (if available) or
    parsed from the exit code and summary line.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(generic_test_dir),
        "-m",
        marker,
        f"--db={db_name}",
        "--cache-clear",
        "--ignore=tests/support/",
        "--no-header",
    ]

    if verbose:
        cmd.append("-v")
    else:
        cmd.extend(["--tb=no", "-q"])

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse summary from pytest output
    passed = failed = errors = skipped = 0
    for line in result.stdout.splitlines():
        line = line.strip()
        # Match pytest summary lines like "42 passed", "3 failed, 2 passed"
        if "passed" in line or "failed" in line or "error" in line:
            # This is likely the summary line
            import re

            counts = re.findall(r"(\d+) (\w+)", line)
            for count_str, label in counts:
                count = int(count_str)
                if label == "passed":
                    passed = count
                elif label == "failed":
                    failed = count
                elif label in ("error", "errors"):
                    errors = count
                elif label in ("skipped", "deselected"):
                    skipped = count

    total = passed + failed + errors

    if result.returncode == 0:
        status = "PASS"
    elif result.returncode == 5:
        # Exit code 5 means no tests collected
        status = "SKIP"
        return CapabilityResult(
            name=marker,
            status=status,
            reason="no tests collected",
        )
    else:
        status = "FAIL"

    return CapabilityResult(
        name=marker,
        status=status,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        total=total,
    )


def _print_conformance_report(
    provider_name: str,
    provider_class_name: str,
    results: list[CapabilityResult],
    skipped_markers: list[str],
) -> None:
    """Print a formatted conformance report to stdout."""
    header = f"Conformance Report: {provider_name}"
    print(f"\n{header}")
    print("=" * len(header))
    print()
    print(f"{'Capability':<24} {'Status':<10} {'Tests'}")
    print("-" * 56)

    total_passed = 0
    total_failed = 0
    total_errors = 0
    capabilities_passed = 0
    capabilities_failed = 0

    for r in results:
        if r.status == "PASS":
            test_info = f"{r.passed}/{r.total}"
            capabilities_passed += 1
        elif r.status == "FAIL":
            test_info = f"{r.passed}/{r.total} ({r.failed} failed"
            if r.errors:
                test_info += f", {r.errors} errors"
            test_info += ")"
            capabilities_failed += 1
        else:
            test_info = f"({r.reason})" if r.reason else ""

        total_passed += r.passed
        total_failed += r.failed
        total_errors += r.errors

        print(f"{r.name:<24} {r.status:<10} {test_info}")

    for marker in skipped_markers:
        print(f"{marker:<24} {'SKIP':<10} (not declared)")

    print("-" * 56)
    skip_count = len(skipped_markers)
    print(
        f"Total: {total_passed} passed, {total_failed} failed, "
        f"{total_errors} errors, {skip_count} capabilities skipped"
    )
    print()


@app.command("test-adapter")
def test_adapter(
    provider: Annotated[
        str, typer.Option(help="Provider name to test (e.g. memory, postgresql)")
    ],
    uri: Annotated[
        str,
        typer.Option(help="Database connection URI (default: provider's default)"),
    ] = "",
    capabilities: Annotated[
        Optional[str],
        typer.Option(
            help="Comma-separated capabilities to test (default: all declared)"
        ),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    test_dir: Annotated[
        Optional[str],
        typer.Option(
            help="Path to generic test directory (default: built-in tests)",
        ),
    ] = None,
) -> None:
    """Run the generic conformance test suite against a database provider.

    Tests are automatically selected based on the provider's declared
    capabilities. Results show which capability areas pass or fail.

    Examples:

        protean test test-adapter --provider=memory

        protean test test-adapter --provider=postgresql --uri="postgresql://localhost/test"

        protean test test-adapter --provider=memory --capabilities=basic_storage,transactional

        protean test test-adapter --provider=postgresql --uri="postgresql://localhost/test" -v
    """
    from protean.port.provider import ProviderRegistry

    # 1. Verify provider is registered
    try:
        ProviderRegistry.get(provider)
    except Exception as e:
        print(f"Error: {e}")
        raise typer.Exit(code=1)

    # 2. Get provider capabilities (instantiate temporarily to access property)
    #    We need a minimal domain to instantiate the provider for capabilities
    try:
        from protean.domain import Domain

        domain = Domain(name="ConformanceTest")

        # Configure the provider
        db_config: dict[str, str | dict] = {"provider": provider}
        if uri:
            db_config["database_uri"] = uri
        domain.config["databases"]["default"] = db_config

        domain._initialize()

        with domain.domain_context():
            provider_instance = domain.providers["default"]
            provider_capabilities = provider_instance.capabilities
            provider_class_name = provider_instance.__class__.__name__
    except Exception as e:
        print(f"Error initializing provider '{provider}': {e}")
        raise typer.Exit(code=1)

    # 3. Determine which capabilities to test
    requested: list[str] | None = None
    if capabilities:
        requested = [c.strip() for c in capabilities.split(",")]
        # Validate requested capabilities
        for cap in requested:
            if cap not in CAPABILITY_MARKER_MAP:
                valid = ", ".join(sorted(CAPABILITY_MARKER_MAP.keys()))
                print(f"Error: Unknown capability '{cap}'. Valid capabilities: {valid}")
                raise typer.Exit(code=1)

    markers_to_run, markers_to_skip = _get_applicable_markers(
        provider_capabilities, requested
    )

    if not markers_to_run:
        print(f"No applicable capabilities to test for provider '{provider}'.")
        if markers_to_skip:
            print(f"Skipped capabilities (not declared): {', '.join(markers_to_skip)}")
        raise typer.Exit(code=0)

    # 4. Determine test directory
    generic_dir = Path(test_dir) if test_dir else GENERIC_TEST_DIR
    if not generic_dir.is_dir():
        print(f"Error: Generic test directory not found: {generic_dir}")
        raise typer.Exit(code=1)

    # Determine the --db flag value (uppercase provider name)
    db_name = provider.upper()

    print(
        f"Running conformance tests for provider '{provider}' "
        f"({provider_class_name})..."
    )
    print(f"Capabilities to test: {', '.join(markers_to_run)}")
    if markers_to_skip:
        print(f"Capabilities to skip: {', '.join(markers_to_skip)}")
    print()

    # 5. Run tests per capability
    results: list[CapabilityResult] = []
    has_failures = False

    for marker in markers_to_run:
        if verbose:
            print(f"Testing capability: {marker}...")

        cap_result = _run_pytest_for_marker(
            marker=marker,
            db_name=db_name,
            generic_test_dir=generic_dir,
            verbose=verbose,
        )
        results.append(cap_result)

        if cap_result.status == "FAIL":
            has_failures = True

    # 6. Print report
    _print_conformance_report(provider, provider_class_name, results, markers_to_skip)

    if has_failures:
        raise typer.Exit(code=1)
