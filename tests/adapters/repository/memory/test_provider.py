def test_provider_is_alive(test_domain):
    """Test ``is_alive`` method"""
    assert test_domain.providers["default"].is_alive()
