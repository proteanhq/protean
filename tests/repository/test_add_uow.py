import mock

from .elements import Person


@mock.patch("protean.core.repository.UnitOfWork.start")
@mock.patch("protean.core.repository.UnitOfWork.commit")
def test_that_method_is_enclosed_in_uow(mock_commit, mock_start, test_domain):
    mock_parent = mock.Mock()

    mock_parent.attach_mock(mock_start, "m1")
    mock_parent.attach_mock(mock_commit, "m2")

    test_domain.register(Person)
    test_domain.init(traverse=False)
    with test_domain.domain_context():
        person = Person(first_name="John", last_name="Doe", age=29)
        test_domain.repository_for(Person).add(person)

    mock_parent.assert_has_calls(
        [
            mock.call.m1(),
            mock.call.m2(),
        ]
    )
