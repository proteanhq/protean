import pytest

from protean.core.exceptions import ValidationError

from .elements import Account, Author


class TestReferenceFieldAssociation:

    @pytest.fixture
    def test_domain(self):
        from protean.domain import Domain
        domain = Domain('Test')
        domain.config.from_object('tests.aggregate.config')

        with domain.domain_context():
            yield domain

    @pytest.fixture(autouse=True)
    def run_around_tests(self, test_domain):
        test_domain.register(Account)
        test_domain.register(Author)

        yield

        test_domain.get_provider('default')._data_reset()

    def test_initalization_of_an_entity_containing_reference_field(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        author = Author(first_name='John', last_name='Doe', account=account)

        assert all(key in author.__dict__ for key in ['first_name', 'last_name', 'account_email'])
        assert author.account.email == account.email

    def test_successful_save_of_entity_with_reference_field(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        author = Author(first_name='John', last_name='Doe', account=account)

        assert not author.state_.is_persisted
        test_domain.get_dao(Author).save(author)

        assert author.state_.is_persisted

    @pytest.mark.skip
    def test_that_assignment_fails_when_an_invalid_entity_type_is_assigned_to_a_relation(self, test_domain):
        class DummyAccount(Account):
            pass

        account = DummyAccount(email='john.doe@gmail.com', password='a1b2c3')
        with pytest.raises(ValidationError):
            Author(first_name='John', last_name='Doe', account=account)

    def test_the_presence_of_shadow_attribute_backing_the_association(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)
        author = Author(first_name='John', last_name='Doe', account=account)
        test_domain.get_dao(Author).save(author)

        assert all(key in author.__dict__ for key in ['account', 'account_email'])
        assert author.account.email == account.email
        assert author.account_email == account.email

    def test_save_after_value_assignment_during_initialization(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)
        author = Author(first_name='John', last_name='Doe', account=account)
        test_domain.get_dao(Author).save(author)

        assert all(key in author.__dict__ for key in ['account', 'account_email'])
        assert author.account.email == account.email
        assert author.account_email == account.email

    def test_save_after_explicit_reference_value_assignment(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)

        author = Author(first_name='John', last_name='Doe')
        assert any(key in author.__dict__ for key in ['account', 'account_email']) is False

        # Explicitly assign value to reference field
        author.account = account
        test_domain.get_dao(Author).save(author)

        assert all(key in author.__dict__ for key in ['account', 'account_email'])
        assert author.account_email == account.email

    def test_fetch_after_save_and_ensure_reference_is_not_auto_loaded(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)
        author = Author(first_name='John', last_name='Doe', account=account)
        test_domain.get_dao(Author).save(author)

        author = test_domain.get_dao(Author).get(author.id)
        # Reference attribute is not loaded automatically
        assert 'account' not in author.__dict__
        assert author.account_email == account.email

        # Accessing attribute shows it up in __dict__
        getattr(author, 'account')
        assert 'account' in author.__dict__

    def test_value_assignment_via_shadow_attribute_during_initialization(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)

        author = Author(first_name='John', last_name='Doe', account_email=account.email)
        assert 'account_email' in author.__dict__
        assert 'account' not in author.__dict__

        test_domain.get_dao(Author).save(author)

        assert author.account.email == account.email
        assert author.account_email == account.email

        # This `keys` test coming after checking `account_email` values is important
        #   because accessing the property will load the key into __dict__
        assert all(key in author.__dict__ for key in ['account', 'account_email'])

    def test_value_assignment_via_shadow_attribute_post_initialization(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)

        author = Author(first_name='John', last_name='Doe')
        author.account_email = account.email
        assert 'account' not in author.__dict__

        test_domain.get_dao(Author).save(author)

        assert author.account.email == account.email
        assert author.account_email == account.email

        # This `keys` test coming after checking `account_email` values is important
        #   because accessing the property will load the key into __dict__
        assert 'account' in author.__dict__

    def test_that_resetting_reference_field_resets_shadow_attribute_too(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)
        author = Author(first_name='John', last_name='Doe', account=account)

        assert author.account.email == account.email
        assert author.account_email == account.email

        author.account = None
        assert any(key in author.__dict__ for key in ['account', 'account_email']) is False
        assert author.account is None
        assert 'account_email' not in author.__dict__

    def test_that_resetting_shadow_attribute_resets_reference_field_too(self, test_domain):
        account = Account(email='john.doe@gmail.com', password='a1b2c3')
        test_domain.get_dao(Account).save(account)
        author = Author(first_name='John', last_name='Doe', account=account)

        assert author.account.email == account.email
        assert author.account_email == account.email

        author.account_email = None

        assert any(key in author.__dict__ for key in ['account', 'account_email']) is False
        assert author.account is None
        assert 'account_email' not in author.__dict__

    # @pytest.mark.skip
    # def test_reference_reset_association_by_del(self, test_domain):
    #     """Test that the reference field and shadow attribute are reset together"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
    #     assert dog.owner_id == human.id
    #     assert dog.owner.id == human.id

    #     del dog.owner
    #     assert any(
    #         key in dog.__dict__ for key in ['owner', 'owner_id']) is False
    #     assert dog.owner is None
    #     assert dog.owner_id is None

    # @pytest.mark.skip
    # def test_reference_reset_shadow_field_by_del(self, test_domain):
    #     """Test that the reference field and shadow attribute are reset together"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
    #     assert dog.owner_id == human.id
    #     assert dog.owner.id == human.id

    #     del dog.owner_id
    #     assert any(
    #         key in dog.__dict__ for key in ['owner', 'owner_id']) is False
    #     assert dog.owner is None
    #     assert dog.owner_id is None

    # @pytest.mark.skip
    # def test_via(self, test_domain):
    #     """Test successful save with an entity linked by via"""
    #     human = test_domain.get_repository(Human).create(
    #         first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = test_domain.get_repository(DogRelatedByEmail).create(
    #         id=1, name='John Doe', age=10, owner=human)
    #     assert all(key in dog.__dict__ for key in ['owner', 'owner_email'])
    #     assert hasattr(dog, 'owner_email')
    #     assert dog.owner_email == human.email

    # @pytest.mark.skip
    # def test_via_with_shadow_attribute_assign(self, test_domain):
    #     """Test successful save with an entity linked by via"""
    #     human = test_domain.get_repository(Human).create(
    #         first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = DogRelatedByEmail(id=1, name='John Doe', age=10)
    #     dog.owner_email = human.email
    #     assert 'owner' not in dog.__dict__
    #     test_domain.get_repository(DogRelatedByEmail).save(dog)
    #     assert hasattr(dog, 'owner_email')
    #     assert dog.owner_email == human.email

    # @mock.patch('protean.core.repository.dao.BaseDAO.find_by')
    # @pytest.mark.skip
    # def test_caching(self, find_by_mock, test_domain):
    #     """Test that subsequent accesses after first retrieval don't fetch record again"""
    #     human = test_domain.get_repository(Human).create(
    #         first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner_id=human.id)

    #     for _ in range(3):
    #         getattr(dog, 'owner')
    #     assert find_by_mock.call_count == 1
