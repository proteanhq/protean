import pytest

from protean.globals import current_domain

from .elements import Person


@pytest.mark.postgresql
class TestSchemaSwitch:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_schema_switch(self, test_domain):
        repo = test_domain.repository_for(Person)
        assert repo._provider._metadata.schema == "public"

        with current_domain.domain_context(MULTITENANCY=True):
            current_domain.config["DATABASES"]["default"]["SCHEMA"] = "private"

            repo1 = current_domain.repository_for(Person)
            assert repo1._provider._metadata.schema == "private"

        # FIXME Reset the database info to default outside the context
        # repo2 = test_domain.repository_for(Person)
        # assert repo2._provider._metadata.schema == "public"
