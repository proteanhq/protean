"""Tests for IRBuilder database model extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_database_model_domain


@pytest.fixture
def db_model_ir():
    """Return full IR for the database model test domain."""
    domain = build_database_model_domain()
    builder = IRBuilder(domain)
    return builder.build()


@pytest.fixture
def customer_cluster(db_model_ir):
    """Return the Customer aggregate cluster from the IR."""
    clusters = db_model_ir["clusters"]
    for cluster_fqn, cluster in clusters.items():
        if cluster["aggregate"]["name"] == "Customer":
            return cluster
    pytest.fail("Customer cluster not found in IR")


@pytest.fixture
def database_models(customer_cluster):
    """Return the database_models dict from the Customer cluster."""
    return customer_cluster["database_models"]


@pytest.mark.no_test_domain
class TestDatabaseModelExtraction:
    """Verify _extract_database_model() produces correct IR dicts."""

    def test_database_models_present(self, database_models):
        assert len(database_models) == 2

    def test_customer_model_element_type(self, database_models):
        model = self._find_model(database_models, "CustomerModel")
        assert model["element_type"] == "DATABASE_MODEL"

    def test_customer_model_name(self, database_models):
        model = self._find_model(database_models, "CustomerModel")
        assert model["name"] == "CustomerModel"

    def test_customer_model_fqn(self, database_models):
        model = self._find_model(database_models, "CustomerModel")
        assert "CustomerModel" in model["fqn"]

    def test_customer_model_part_of(self, database_models, customer_cluster):
        model = self._find_model(database_models, "CustomerModel")
        assert model["part_of"] == customer_cluster["aggregate"]["fqn"]

    def test_customer_model_schema_name(self, database_models):
        model = self._find_model(database_models, "CustomerModel")
        assert model["schema_name"] == "customers"

    def test_customer_model_database_default(self, database_models):
        model = self._find_model(database_models, "CustomerModel")
        assert "database" not in model

    def test_report_model_database_custom(self, database_models):
        model = self._find_model(database_models, "CustomerReportModel")
        assert model["database"] == "reporting"

    def test_report_model_schema_name(self, database_models):
        model = self._find_model(database_models, "CustomerReportModel")
        assert model["schema_name"] == "customer_reports"

    def test_report_model_part_of(self, database_models, customer_cluster):
        model = self._find_model(database_models, "CustomerReportModel")
        assert model["part_of"] == customer_cluster["aggregate"]["fqn"]

    def test_keys_sorted(self, database_models):
        for model_fqn, model in database_models.items():
            keys = list(model.keys())
            assert keys == sorted(keys), (
                f"Keys not sorted for model '{model_fqn}': {keys}"
            )

    @staticmethod
    def _find_model(database_models: dict, name: str) -> dict:
        """Find a database model dict by class name."""
        for model_fqn, model in database_models.items():
            if model["name"] == name:
                return model
        pytest.fail(f"Database model '{name}' not found")
