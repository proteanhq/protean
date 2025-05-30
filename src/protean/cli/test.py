import os
import subprocess
import webbrowser
from contextlib import suppress
from enum import Enum
from pathlib import Path

import typer
from typing_extensions import Annotated

REPORT_PATH = Path("diff_coverage_report.html")
GOOGLE_FONT = "https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600&display=swap"
STYLE_BLOCK = f"""
<!-- Injected by protean CLI -->
<link href="{GOOGLE_FONT}" rel="stylesheet">
<style>
    body {{
        font-family: "Source Sans Pro", sans-serif;
        margin: 20px;
        background-color: #f8f9fa;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        background: #fff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }}
    th, td {{
        padding: 12px 15px;
        border: 1px solid #dee2e6;
        text-align: left;
    }}
    th {{
        background-color: #343a40;
        color: white;
    }}
    tr:nth-child(even) {{
        background-color: #f2f2f2;
    }}
    .low-coverage {{
        color: red;
        font-weight: bold;
    }}
    .high-coverage {{
        color: green;
        font-weight: bold;
    }}
</style>
"""


class TestCategory(str, Enum):
    CORE = "CORE"
    EVENTSTORE = "EVENTSTORE"
    DATABASE = "DATABASE"
    BROKER = "BROKER"
    COVERAGE = "COVERAGE"
    FULL = "FULL"


app = typer.Typer()


# ------------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------------ #
def _run(cmd: list[str]) -> int:
    """Run a command, streaming output, and return its exit code."""
    return subprocess.call(cmd)


def _inject_style(path: Path, style_block: str = STYLE_BLOCK) -> None:
    """Insert the style block before </head>."""
    with suppress(FileNotFoundError):
        html = path.read_text(encoding="utf-8")
        if "</head>" in html and style_block not in html:
            html = html.replace("</head>", f"{style_block}\n</head>")
            path.write_text(html, encoding="utf-8")


# ------------------------------------------------------------------------ #
# Existing helpers (only small change: return accumulated status)
# ------------------------------------------------------------------------ #
def run_full(subprocess, coverage_command, pytest_command) -> int:
    """Run all test combos under coverage.
    Returns the _highest_ exit code seen (0 == success)."""
    exit_status = 0  # 0 means success so far

    def track(rc: int) -> None:
        nonlocal exit_status
        exit_status |= rc  # keep the highest non-zero code

    # fresh slate
    track(_run(["coverage", "erase"]))

    # full matrix
    track(
        _run(
            coverage_command
            + pytest_command
            + [
                "--slow",
                "--sqlite",
                "--postgresql",
                "--elasticsearch",
                "--redis",
                "--message_db",
                "tests",
            ]
        )
    )

    # database permutations
    for db in ["MEMORY", "POSTGRESQL", "SQLITE"]:
        print(f"Running tests for DB: {db}…")
        track(
            _run(coverage_command + pytest_command + ["-m", "database", f"--db={db}"])
        )

    # event-store permutations
    for store in ["MESSAGE_DB"]:
        print(f"Running tests for EVENTSTORE: {store}…")
        track(
            _run(
                coverage_command
                + pytest_command
                + ["-m", "eventstore", f"--store={store}"]
            )
        )

    # gather coverage
    if exit_status == 0:  # only combine if all tests passed
        print("\nCombining coverage data and generating report…")
        track(_run(["coverage", "combine"]))
        track(_run(["coverage", "xml"]))
        track(_run(["coverage", "report"]))
    else:
        print("\n❌ Skipping coverage combine – some tests failed.")

    return exit_status


@app.callback(invoke_without_command=True)
def test(
    category: Annotated[
        TestCategory, typer.Option("-c", "--category", case_sensitive=False)
    ] = TestCategory.CORE,
):
    coverage_command = ["coverage", "run", "--parallel-mode", "-m"]
    pytest_command = ["pytest", "--cache-clear", "--ignore=tests/support/"]

    # Each branch now captures exit code and, in COVERAGE mode,
    # decides whether to post-process coverage.
    match category.value:
        case "EVENTSTORE":
            rc = 0
            for store in ["MEMORY", "MESSAGE_DB"]:
                print(f"Running tests for EVENTSTORE: {store}…")
                rc |= _run(pytest_command + ["-m", "eventstore", f"--store={store}"])
        case "DATABASE":
            rc = 0
            for db in ["MEMORY", "POSTGRESQL", "SQLITE"]:
                print(f"Running tests for DATABASE: {db}…")
                rc |= _run(pytest_command + ["-m", "database", f"--db={db}"])
        case "BROKER":
            rc = 0
            for broker in ["INLINE"]:
                print(f"Running tests for BROKER: {broker}…")
                rc |= _run(pytest_command + ["-m", "broker", f"--broker={broker}"])
        case "FULL":
            rc = run_full(subprocess, coverage_command, pytest_command)
        case "COVERAGE":
            rc = run_full(subprocess, coverage_command, pytest_command)

            # ------------------------------------------------------------------
            # Only generate & style diff-cover report if *everything* passed
            # ------------------------------------------------------------------
            if rc == 0:
                rc |= _run(
                    [
                        "diff-cover",
                        "coverage.xml",
                        "--compare-branch=main",
                        "--html-report",
                        REPORT_PATH.name,
                    ]
                )
                _inject_style(REPORT_PATH)

                path = os.path.abspath(REPORT_PATH.name)
                url = f"file://{path}"
                webbrowser.open(url)
            else:
                print("\n❌ Tests failed – skipping diff-cover report.")
        case _:
            print("Running core tests…")
            rc = _run(pytest_command)

    # Exit Typer CLI with the highest non-zero status we saw
    if rc != 0:
        raise typer.Exit(code=rc)
