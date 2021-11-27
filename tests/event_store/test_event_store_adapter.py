def test_domain_has_an_event_store_attribute(test_domain):
    assert test_domain.event_store is not None
