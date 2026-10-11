# --8<-- [start:test_domain_fixture]
def test_domain_initialization(test_domain):
    assert test_domain.name == "Test"
    assert test_domain.config["testing"] is True


# --8<-- [end:test_domain_fixture]
