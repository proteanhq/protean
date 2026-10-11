"""Check what docs/reference/cli/ir.md says about reading the IR from Python.

The page says ``domain.to_ir()`` returns the same document that
``protean ir show`` prints as JSON. The example builds an ``Ordering`` domain
with an ``Order`` aggregate and an ``OrderPlaced`` event, then calls
``domain.init()`` and ``domain.to_ir()``.
"""

import json

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.docs.support import load_example, module_name_for

pytestmark = pytest.mark.no_test_domain

EXAMPLE = "reference/cli/ir/001.py"


@pytest.fixture
def example():
    return load_example("reference/cli/ir/001.py")


def test_to_ir_returns_the_documented_sections(example):
    for section in (
        "domain",
        "clusters",
        "projections",
        "flows",
        "elements",
        "diagnostics",
    ):
        assert section in example.ir


def test_to_ir_describes_the_example_domain(example):
    module = module_name_for(EXAMPLE)

    assert example.ir["domain"]["name"] == "Ordering"
    assert example.ir["elements"]["AGGREGATE"] == [f"{module}.Order"]
    assert example.ir["elements"]["EVENT"] == [f"{module}.OrderPlaced"]
    cluster = example.ir["clusters"][f"{module}.Order"]
    assert set(cluster["aggregate"]["fields"]) == {"id", "customer_id", "total"}


def test_to_ir_matches_the_json_that_ir_show_prints(example):
    # The example is registered in sys.modules under its module name, so the
    # CLI loads the same domain object the example built.
    result = CliRunner().invoke(app, ["ir", "show", "-d", module_name_for(EXAMPLE)])

    assert result.exit_code == 0, result.output
    printed = json.loads(result.stdout)
    # The timestamp records when each document was built, to the second.
    printed.pop("generated_at")
    built = dict(example.ir)
    built.pop("generated_at")
    assert printed == built
