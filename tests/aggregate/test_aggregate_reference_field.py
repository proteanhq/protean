import pytest

from protean.exceptions import ValidationError
from protean.utils.reflection import attributes

from .elements import Account, Author


class TestReferenceFieldAssociation:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(Author, part_of=Account)
        test_domain.init(traverse=False)

    def test_initialization_of_an_entity_containing_reference_field(self, test_domain):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        author = Author(first_name="John", last_name="Doe", account=account)

        assert all(
            key in author.__dict__
            for key in ["first_name", "last_name", "account_email"]
        )
        assert author.account.email == account.email

    def test_successful_save_of_entity_with_reference_field(self, test_domain):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        author = Author(first_name="John", last_name="Doe", account=account)

        assert not author.state_.is_persisted
        test_domain.repository_for(Author)._dao.save(author)

        assert author.state_.is_persisted

    @pytest.mark.skip
    def test_that_assignment_fails_when_an_invalid_entity_type_is_assigned_to_a_relation(
        self, test_domain
    ):
        class DummyAccount(Account):
            pass

        account = DummyAccount(email="john.doe@gmail.com", password="a1b2c3")
        with pytest.raises(ValidationError):
            Author(first_name="John", last_name="Doe", account=account)

    def test_the_presence_of_shadow_attribute_backing_the_association(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account=account)
        test_domain.repository_for(Author)._dao.save(author)

        assert all(key in author.__dict__ for key in ["account", "account_email"])
        assert author.account.email == account.email
        assert author.account_email == account.email

    def test_save_after_value_assignment_during_initialization(self, test_domain):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account=account)
        test_domain.repository_for(Author)._dao.save(author)

        assert all(key in author.__dict__ for key in ["account", "account_email"])
        assert author.account.email == account.email
        assert author.account_email == account.email

    def test_save_after_explicit_reference_value_assignment(self, test_domain):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)

        author = Author(first_name="John", last_name="Doe")
        assert (
            any(key in author.__dict__ for key in ["account", "account_email"]) is False
        )

        # Explicitly assign value to reference field
        author.account = account
        test_domain.repository_for(Author)._dao.save(author)

        assert all(key in author.__dict__ for key in ["account", "account_email"])
        assert author.account_email == account.email

    def test_fetch_after_save_and_ensure_reference_is_not_auto_loaded(
        self, test_domain
    ):
        account = Account(
            email="john.doe@gmail.com",
            password="a1b2c3",
            author=Author(first_name="John", last_name="Doe"),
        )
        test_domain.repository_for(Account).add(account)

        author = test_domain.repository_for(Account).get(account.email).author
        # Reference attribute is not loaded automatically
        assert "account" not in author.__dict__
        assert author.account_email == account.email

        # Accessing attribute shows it up in __dict__
        getattr(author, "account")
        assert "account" in author.__dict__

    def test_value_assignment_via_shadow_attribute_during_initialization(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)

        author = Author(first_name="John", last_name="Doe", account_email=account.email)
        assert "account_email" in author.__dict__
        assert "account" not in author.__dict__

        test_domain.repository_for(Author)._dao.save(author)

        assert author.account.email == account.email
        assert author.account_email == account.email

        # This `keys` test coming after checking `account_email` values is important
        #   because accessing the property will load the key into __dict__
        assert all(key in author.__dict__ for key in ["account", "account_email"])

    def test_value_assignment_via_shadow_attribute_post_initialization(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)

        author = Author(first_name="John", last_name="Doe")
        author.account_email = account.email
        assert "account" not in author.__dict__

        test_domain.repository_for(Author)._dao.save(author)

        assert author.account.email == account.email
        assert author.account_email == account.email

        # This `keys` test coming after checking `account_email` values is important
        #   because accessing the property will load the key into __dict__
        assert "account" in author.__dict__

    def test_that_resetting_reference_field_resets_shadow_attribute_too(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account=account)

        assert author.account.email == account.email
        assert author.account_email == account.email

        author.account = None
        assert (
            any(key in author.__dict__ for key in ["account", "account_email"]) is False
        )
        assert author.account is None
        assert "account_email" not in author.__dict__

    def test_that_setting_shadow_attribute_to_none_resets_reference_field_too(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account=account)

        assert author.account.email == account.email
        assert author.account_email == account.email

        assert "account_email" in attributes(author)
        author.account_email = None

        assert (
            any(key in author.__dict__ for key in ["account", "account_email"]) is False
        )
        assert author.account is None
        assert author.account_email is None
        assert "account_email" not in author.__dict__

    def test_that_resetting_the_reference_field_resets_shadow_attribute_too(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account=account)

        del author.account
        assert (
            any(key in author.__dict__ for key in ["account", "account_email"]) is False
        )
        assert author.account is None
        assert author.account_email is None
        assert "account_email" not in author.__dict__

    def test_that_resetting_the_shadow_attribute_resets_reference_field_too(
        self, test_domain
    ):
        account = Account(email="john.doe@gmail.com", password="a1b2c3")
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account=account)

        del author.account_email
        assert (
            any(key in author.__dict__ for key in ["account", "account_email"]) is False
        )
        assert author.account is None
        assert author.account_email is None
        assert "account_email" not in author.__dict__

    def test_that_subsequent_accesses_after_first_retrieval_do_not_fetch_record_again(
        self, test_domain
    ):
        account = Account(
            email="john.doe@gmail.com", password="a1b2c3", username="johndoe"
        )
        test_domain.repository_for(Account)._dao.save(account)
        author = Author(first_name="John", last_name="Doe", account_email=account.email)

        for _ in range(3):
            getattr(author, "account")
