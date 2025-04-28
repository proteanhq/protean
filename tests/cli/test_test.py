from unittest.mock import call

import pytest
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
                call(["open", "diff_coverage_report.html"]),
            ],
            11,  # 5 calls + 6 for coverage operations (erase, combine, report)
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
def test_command(mock_subprocess_call, category, expected_calls, call_count):
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
