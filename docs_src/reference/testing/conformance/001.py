# --8<-- [start:opt_in]
# conftest.py
pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]
# --8<-- [end:opt_in]


def test_the_default_adapter_under_test_is_memory(test_domain, db_config):
    assert db_config["provider"] == "memory"
    assert test_domain.providers["default"].conn_info["provider"] == "memory"
