import pytest

from .elements import Account, Author


class TestReferenceFieldAssociation:

    @pytest.fixture
    def test_domain(self):
        from protean.domain import Domain
        domain = Domain('Test', 'tests.aggregate.config')

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

        assert all(key in author.__dict__ for key in ['first_name', 'last_name', 'account_id'])
        assert author.account.id == account.id
        assert author.account_id == account.id

    # @pytest.mark.skip
    # def test_init_with_string_reference(self, test_domain):
    #     """Test successful RelatedDog initialization"""
    #     human = test_domain.get_repository(Human).create(
    #         first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog2(id=1, name='John Doe', age=10, owner=human)
    #     assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
    #     assert dog.owner.id == human.id
    #     assert dog.owner_id == human.id
    #     assert not hasattr(human,
    #                        'dog')  # Reverse linkages are not provided by default

    # @pytest.mark.skip
    # def test_save(self, test_domain):
    #     """Test successful RelatedDog save"""
    #     human = test_domain.get_repository(Human).create(
    #         first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
    #     assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
    #     test_domain.get_repository(RelatedDog).save(dog)
    #     assert dog.id is not None
    #     assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])

    # @pytest.mark.skip
    # def test_unsaved_entity_init(self):
    #     """Test that initialization fails when an unsaved entity is assigned to a relation"""
    #     with pytest.raises(ValueError):
    #         human = Human(first_name='Jeff', last_name='Kennedy',
    #                       email='jeff.kennedy@presidents.com')
    #         RelatedDog(id=1, name='John Doe', age=10, owner=human)

    # @pytest.mark.skip
    # def test_unsaved_entity_assign(self):
    #     """Test that assignment fails when an unsaved entity is assigned to a relation"""
    #     with pytest.raises(ValueError):
    #         human = Human(first_name='Jeff', last_name='Kennedy',
    #                       email='jeff.kennedy@presidents.com')

    #         dog = RelatedDog(id=1, name='John Doe', age=10)
    #         assert any(
    #             key in dog.__dict__ for key in ['owner', 'owner_id']) is False
    #         dog.owner = human

    # @pytest.mark.skip
    # def test_invalid_entity_type(self, test_domain):
    #     """Test that assignment fails when an invalid entity type is assigned to a relation"""
    #     with pytest.raises(ValidationError):
    #         dog = test_domain.get_repository(Dog).create(name='Johnny', owner='John')
    #         related_dog = RelatedDog(id=1, name='John Doe', age=10)
    #         related_dog.owner = dog

    # @pytest.mark.skip
    # def test_shadow_attribute(self, test_domain):
    #     """Test identifier backing the association"""
    #     human = test_domain.get_repository(Human).create(
    #         first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
    #     assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
    #     assert human.id is not None
    #     assert dog.owner_id == human.id

    # @pytest.mark.skip
    # def test_save_after_assign(self, test_domain):
    #     """Test saving after assignment (post init)"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10)
    #     assert any(
    #         key in dog.__dict__ for key in ['owner', 'owner_id']) is False
    #     dog.owner = human
    #     test_domain.get_repository(RelatedDog).save(dog)
    #     assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
    #     assert dog.owner_id == human.id

    # @pytest.mark.skip
    # def test_fetch_after_save(self, test_domain):
    #     """Test fetch after save and ensure reference is not auto-loaded"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10)
    #     dog.owner = human
    #     test_domain.get_repository(RelatedDog).save(dog)

    #     dog2 = test_domain.get_repository(RelatedDog).get(dog.id)
    #     # Reference attribute is not loaded automatically
    #     assert 'owner' not in dog2.__dict__
    #     assert dog2.owner_id == human.id

    #     # Accessing attribute shows it up in __dict__
    #     getattr(dog2, 'owner')
    #     assert 'owner' in dog2.__dict__

    # @pytest.mark.skip
    # def test_shadow_attribute_init(self, test_domain):
    #     """Test identifier backing the association"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner_id=human.id)
    #     assert 'owner_id' in dog.__dict__
    #     assert 'owner' not in dog.__dict__
    #     test_domain.get_repository(RelatedDog).save(dog)
    #     assert dog.owner_id == human.id
    #     assert dog.owner.id == human.id
    #     assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])

    # @pytest.mark.skip
    # def test_shadow_attribute_assign(self, test_domain):
    #     """Test identifier backing the association"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10)
    #     dog.owner_id = human.id
    #     assert 'owner' not in dog.__dict__
    #     test_domain.get_repository(RelatedDog).save(dog)
    #     assert dog.owner_id == human.id
    #     assert dog.owner.id == human.id
    #     assert 'owner' in dog.__dict__

    # @pytest.mark.skip
    # def test_reference_reset_association_to_None(self, test_domain):
    #     """Test that the reference field and shadow attribute are reset together"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
    #     assert dog.owner_id == human.id
    #     assert dog.owner.id == human.id

    #     dog.owner = None
    #     assert any(
    #         key in dog.__dict__ for key in ['owner', 'owner_id']) is False
    #     assert dog.owner is None
    #     assert dog.owner_id is None

    # @pytest.mark.skip
    # def test_reference_reset_shadow_field_to_None(self, test_domain):
    #     """Test that the reference field and shadow attribute are reset together"""
    #     human = test_domain.get_repository(Human).create(
    #         id=101, first_name='Jeff', last_name='Kennedy',
    #         email='jeff.kennedy@presidents.com')
    #     dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
    #     assert dog.owner_id == human.id
    #     assert dog.owner.id == human.id

    #     dog.owner_id = None
    #     assert any(
    #         key in dog.__dict__ for key in ['owner', 'owner_id']) is False
    #     assert dog.owner is None
    #     assert dog.owner_id is None

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

