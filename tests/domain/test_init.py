import mock


def test_domain_init_calls_validate_domain(test_domain):
    mock_validate_domain = mock.Mock()
    test_domain._validate_domain = mock_validate_domain
    test_domain.init(traverse=False)
    mock_validate_domain.assert_called_once()


def test_domain_init_calls_traverse(test_domain):
    mock_traverse = mock.Mock()
    test_domain._traverse = mock_traverse
    test_domain.init()
    mock_traverse.assert_called_once()


def test_domain_init_does_not_call_traverse_when_false(test_domain):
    mock_traverse = mock.Mock()
    test_domain._traverse = mock_traverse
    test_domain.init(traverse=False)
    mock_traverse.assert_not_called()


def test_domain_init_calls_resolve_references(test_domain):
    mock_resolve_references = mock.Mock()
    test_domain._resolve_references = mock_resolve_references
    test_domain.init(traverse=False)
    mock_resolve_references.assert_called_once()
