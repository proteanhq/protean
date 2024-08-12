from unittest.mock import call

import pytest
from typer.testing import CliRunner

from protean.cli import Category, app

runner = CliRunner()


@pytest.fixture
def mock_subprocess_call(mocker):
    return mocker.patch("protean.cli.subprocess.call")


@pytest.mark.parametrize(
    "category,expected_calls",
    [
        (
            Category.EVENTSTORE,
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
        ),
        (
            Category.DATABASE,
            [
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
        ),
        (
            Category.FULL,
            [
                call(
                    [
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "--slow",
                        "--sqlite",
                        "--postgresql",
                        "--elasticsearch",
                        "--redis",
                        "--message_db",
                        "--cov=protean",
                        "--cov-config",
                        ".coveragerc",
                        "tests",
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
        ),
        (
            Category.COVERAGE,
            [
                call(
                    [
                        "pytest",
                        "--cache-clear",
                        "--ignore=tests/support/",
                        "--slow",
                        "--sqlite",
                        "--postgresql",
                        "--elasticsearch",
                        "--redis",
                        "--message_db",
                        "--cov=protean",
                        "--cov-config",
                        ".coveragerc",
                        "tests",
                    ]
                ),
            ],
        ),
        (
            Category.CORE,
            [
                call(["pytest", "--cache-clear", "--ignore=tests/support/"]),
            ],
        ),
    ],
)
def test_command(mock_subprocess_call, category, expected_calls):
    result = runner.invoke(app, ["test", "--category", category.value])

    assert result.exit_code == 0
    assert mock_subprocess_call.call_count == len(expected_calls)
    mock_subprocess_call.assert_has_calls(expected_calls, any_order=True)


def test_default_category(mock_subprocess_call):
    # Test the command with the default category (CORE)
    result = runner.invoke(app, ["test"])

    assert result.exit_code == 0
    mock_subprocess_call.assert_called_once_with(
        ["pytest", "--cache-clear", "--ignore=tests/support/"]
    )


def test_invalid_category(mock_subprocess_call):
    # Test the command with an invalid category (should raise error)
    result = runner.invoke(app, ["test", "--category", "INVALID"])

    assert result.exit_code == 2
    assert (
        "Invalid value for '-c' / '--category': 'INVALID' is not one of "
        in result.output
    )
