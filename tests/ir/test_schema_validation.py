"""Tests that validate generated IR output against the JSON Schema."""

import json
from pathlib import Path

import pytest
from jsonschema import validate, ValidationError

from protean.ir import EXAMPLES_DIR, load_schema
from protean.ir.builder import IRBuilder

from .elements import (
    build_cluster_test_domain,
    build_command_event_test_domain,
    build_database_model_domain,
    build_domain_service_domain,
    build_es_aggregate_domain,
    build_extended_field_test_domain,
    build_field_test_domain,
    build_handler_test_domain,
    build_integration_domain,
    build_process_manager_domain,
    build_status_field_domain,
    build_via_and_min_length_domain,
)


@pytest.fixture(scope="module")
def schema():
    """Load the IR JSON Schema once per module."""
    return load_schema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOMAIN_BUILDERS = [
    pytest.param(build_field_test_domain, id="field_test"),
    pytest.param(build_extended_field_test_domain, id="extended_field_test"),
    pytest.param(build_via_and_min_length_domain, id="via_and_min_length"),
    pytest.param(build_cluster_test_domain, id="cluster_test"),
    pytest.param(build_command_event_test_domain, id="command_event_test"),
    pytest.param(build_handler_test_domain, id="handler_test"),
    pytest.param(build_es_aggregate_domain, id="es_aggregate"),
    pytest.param(build_domain_service_domain, id="domain_service"),
    pytest.param(build_process_manager_domain, id="process_manager"),
    pytest.param(build_status_field_domain, id="status_field"),
    pytest.param(build_database_model_domain, id="database_model"),
    pytest.param(build_integration_domain, id="integration"),
]


def _example_files():
    """Yield parametrized paths for each example JSON file."""
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        yield pytest.param(path, id=path.stem)


# ---------------------------------------------------------------------------
# Test domain IR validates against schema
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestGeneratedIRValidation:
    """Validate IR generated from each test domain against the JSON Schema."""

    @pytest.mark.parametrize("builder", _DOMAIN_BUILDERS)
    def test_generated_ir_validates(self, schema, builder):
        domain = builder()
        ir_builder = IRBuilder(domain)
        ir = ir_builder.build()
        try:
            validate(instance=ir, schema=schema)
        except ValidationError as exc:
            pytest.fail(
                f"IR from {builder.__name__} failed schema validation:\n"
                f"  Path: {'.'.join(str(p) for p in exc.absolute_path)}\n"
                f"  Message: {exc.message}"
            )


# ---------------------------------------------------------------------------
# Example file IR validates against schema
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestExampleFileValidation:
    """Validate shipped example IR files against the JSON Schema."""

    @pytest.mark.parametrize("example_path", _example_files())
    def test_example_validates_against_schema(self, schema, example_path: Path):
        data = json.loads(example_path.read_text(encoding="utf-8"))
        try:
            validate(instance=data, schema=schema)
        except ValidationError as exc:
            pytest.fail(
                f"{example_path.name} failed schema validation:\n"
                f"  Path: {'.'.join(str(p) for p in exc.absolute_path)}\n"
                f"  Message: {exc.message}"
            )
