"""Init-time and runtime raises in ``domain/__init__.py`` and ``domain/config.py``
carry a registered diagnostic code, a fix, and a location.

Each code gets a positive test (it fires at the raise site, with the right code
and a location) and a negative test (the valid path does not raise it). The
positive tests together exercise every one of the raise sites the codes were
attached to.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.projection import BaseProjection
from protean.domain.config import Config2
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import Identifier, String
from protean.utils import DomainObjects

pytestmark = pytest.mark.no_test_domain


class Book(BaseAggregate):
    id = Identifier(identifier=True)
    title = String()


class Summary(BaseProjection):
    id = Identifier(identifier=True)


class Ghost(BaseAggregate):
    """A registered-nowhere aggregate, for the not-registered accessor paths."""

    id = Identifier(identifier=True)


@pytest.fixture
def domain() -> Domain:
    d = Domain(name="Diagnostics")
    d.config["caches"] = {"default": {"provider": "memory"}}
    d.register(Book)
    d.register(Summary)

    @d.projection(cache="default")
    class Cached:
        id = Identifier(identifier=True)

    d.init(traverse=False)
    d.Cached = Cached  # type: ignore[attr-defined]
    return d


# ---------------------------------------------------------------------------
# CONFIG_UNRESOLVED_ENV_VAR
# ---------------------------------------------------------------------------
class TestConfigUnresolvedEnvVar:
    def test_it_fires_for_an_unset_variable(self):
        with pytest.raises(ConfigurationError) as exc:
            Config2._replace_env_var("${PROTEAN_TEST_DEFINITELY_UNSET}")

        assert exc.value.code == "CONFIG_UNRESOLVED_ENV_VAR"
        assert "PROTEAN_TEST_DEFINITELY_UNSET" in exc.value.location
        assert exc.value.fix

    def test_a_placeholder_with_a_default_does_not_fire(self):
        assert Config2._replace_env_var("${PROTEAN_TEST_UNSET|fallback}") == "fallback"


# ---------------------------------------------------------------------------
# CONFIG_AMBIGUOUS_ELEMENT_NAME / CONFIG_ELEMENT_NOT_REGISTERED
# ---------------------------------------------------------------------------
class TestConfigElementLookup:
    def _dup_domain(self) -> Domain:
        d = Domain(name="Dups")
        a1 = type(
            "Dup",
            (BaseAggregate,),
            {
                "__module__": "mod_a",
                "__annotations__": {"id": Identifier(identifier=True)},
            },
        )
        a2 = type(
            "Dup",
            (BaseAggregate,),
            {
                "__module__": "mod_b",
                "__annotations__": {"id": Identifier(identifier=True)},
            },
        )
        d.register(a1)
        d.register(a2)
        d.init(traverse=False)
        return d

    def test_ambiguous_short_name_fires(self):
        d = self._dup_domain()
        with pytest.raises(ConfigurationError) as exc:
            d._get_element_by_name((DomainObjects.AGGREGATE,), "Dup")

        assert exc.value.code == "CONFIG_AMBIGUOUS_ELEMENT_NAME"
        assert exc.value.location == "Domain._get_element_by_name"

    def test_a_unique_name_resolves_without_firing(self, domain):
        record = domain._get_element_by_name((DomainObjects.AGGREGATE,), "Book")
        assert record.cls is Book

    def test_absent_name_fires_not_registered(self, domain):
        with pytest.raises(ConfigurationError) as exc:
            domain._get_element_by_name((DomainObjects.AGGREGATE,), "Nope")

        assert exc.value.code == "CONFIG_ELEMENT_NOT_REGISTERED"
        assert exc.value.location == "Domain._get_element_by_name"

    def test_present_name_wrong_type_fires_not_registered(self, domain):
        # "Book" is registered as an AGGREGATE; asking for it as an EVENT takes
        # the ``else`` branch, distinct from the KeyError branch above.
        with pytest.raises(ConfigurationError) as exc:
            domain._get_element_by_name((DomainObjects.EVENT,), "Book")

        assert exc.value.code == "CONFIG_ELEMENT_NOT_REGISTERED"
        assert exc.value.location == "Domain._get_element_by_name"

    def test_bad_fully_qualified_name_fires_not_registered(self, domain):
        with pytest.raises(ConfigurationError) as exc:
            domain._get_element_by_fully_qualified_name(
                (DomainObjects.AGGREGATE,), "no.such.Thing"
            )

        assert exc.value.code == "CONFIG_ELEMENT_NOT_REGISTERED"
        assert exc.value.location == "Domain._get_element_by_fully_qualified_name"


# ---------------------------------------------------------------------------
# CONFIG_EVENT_STORE_NOT_INITIALIZED
# ---------------------------------------------------------------------------
class TestConfigEventStoreNotInitialized:
    def test_before_init_it_fires(self):
        d = Domain(name="Uninit")
        with pytest.raises(ConfigurationError) as exc:
            d._require_event_store()

        assert exc.value.code == "CONFIG_EVENT_STORE_NOT_INITIALIZED"
        assert exc.value.location == "Domain._require_event_store"

    def test_after_init_it_returns_the_store(self, domain):
        assert domain._require_event_store() is not None


# ---------------------------------------------------------------------------
# USAGE_UNKNOWN_ELEMENT_TYPE
# ---------------------------------------------------------------------------
class TestUsageUnknownElementType:
    def test_an_unknown_type_fires(self, domain):
        with pytest.raises(IncorrectUsageError) as exc:
            domain.factory_for(SimpleNamespace(value="NOPE"))

        assert exc.value.code == "USAGE_UNKNOWN_ELEMENT_TYPE"
        assert exc.value.location == "Domain.factory_for"

    def test_a_known_type_returns_a_factory(self, domain):
        assert domain.factory_for(DomainObjects.AGGREGATE) is not None


# ---------------------------------------------------------------------------
# USAGE_DUPLICATE_DATABASE_MODEL
# ---------------------------------------------------------------------------
class TestUsageDuplicateDatabaseModel:
    def test_a_second_model_for_the_same_target_fires(self):
        d = Domain(name="Models")
        d.register(Book)

        class BookModelA(BaseDatabaseModel):
            pass

        class BookModelB(BaseDatabaseModel):
            pass

        d.register(BookModelA, part_of=Book)
        with pytest.raises(IncorrectUsageError) as exc:
            d.register(BookModelB, part_of=Book)

        assert exc.value.code == "USAGE_DUPLICATE_DATABASE_MODEL"
        assert exc.value.location == "Domain._register_element"

    def test_a_single_model_registers_cleanly(self):
        d = Domain(name="OneModel")
        d.register(Book)

        class BookModelC(BaseDatabaseModel):
            pass

        d.register(BookModelC, part_of=Book)  # no raise
        d.init(traverse=False)


# ---------------------------------------------------------------------------
# USAGE_ENRICHER_NOT_CALLABLE
# ---------------------------------------------------------------------------
class TestUsageEnricherNotCallable:
    @pytest.mark.parametrize(
        "method,location",
        [
            ("register_event_enricher", "Domain.register_event_enricher"),
            ("register_command_enricher", "Domain.register_command_enricher"),
            ("register_aggregate_enricher", "Domain.register_aggregate_enricher"),
        ],
    )
    def test_a_non_callable_enricher_fires(self, domain, method, location):
        with pytest.raises(IncorrectUsageError) as exc:
            getattr(domain, method)(42)

        assert exc.value.code == "USAGE_ENRICHER_NOT_CALLABLE"
        assert exc.value.location == location

    def test_a_callable_enricher_registers(self, domain):
        domain.register_event_enricher(lambda *a, **k: None)  # no raise


# ---------------------------------------------------------------------------
# USAGE_ELEMENT_NOT_REGISTERED
# ---------------------------------------------------------------------------
class TestUsageElementNotRegistered:
    @pytest.mark.parametrize(
        "accessor,location",
        [
            ("repository_for", "Domain.repository_for"),
            ("view_for", "Domain.view_for"),
            ("connection_for", "Domain.connection_for"),
        ],
    )
    def test_a_name_string_fires(self, domain, accessor, location):
        with domain.domain_context():
            with pytest.raises(IncorrectUsageError) as exc:
                getattr(domain, accessor)("SomeName")

        assert exc.value.code == "USAGE_ELEMENT_NOT_REGISTERED"
        assert exc.value.location == location

    def test_create_snapshot_for_an_unregistered_aggregate_fires(self, domain):
        with domain.domain_context():
            with pytest.raises(IncorrectUsageError) as exc:
                domain.create_snapshot(Ghost, "id-1")

        assert exc.value.code == "USAGE_ELEMENT_NOT_REGISTERED"
        assert exc.value.location == "Domain.create_snapshot"

    def test_create_snapshots_for_an_unregistered_aggregate_fires(self, domain):
        with domain.domain_context():
            with pytest.raises(IncorrectUsageError) as exc:
                domain.create_snapshots(Ghost)

        assert exc.value.code == "USAGE_ELEMENT_NOT_REGISTERED"
        assert exc.value.location == "Domain.create_snapshots"

    def test_a_registered_aggregate_gets_a_repository(self, domain):
        with domain.domain_context():
            assert domain.repository_for(Book) is not None


# ---------------------------------------------------------------------------
# USAGE_NOT_A_PROJECTION
# ---------------------------------------------------------------------------
class TestUsageNotAProjection:
    @pytest.mark.parametrize(
        "accessor,location",
        [
            ("view_for", "Domain.view_for"),
            ("connection_for", "Domain.connection_for"),
        ],
    )
    def test_a_non_projection_fires(self, domain, accessor, location):
        with domain.domain_context():
            with pytest.raises(IncorrectUsageError) as exc:
                getattr(domain, accessor)(Book)

        assert exc.value.code == "USAGE_NOT_A_PROJECTION"
        assert exc.value.location == location

    def test_a_projection_gets_a_view(self, domain):
        with domain.domain_context():
            assert domain.view_for(Summary) is not None


# ---------------------------------------------------------------------------
# USAGE_CACHE_BACKED_NO_REPOSITORY
# ---------------------------------------------------------------------------
class TestUsageCacheBackedNoRepository:
    def test_a_cache_backed_projection_fires(self, domain):
        with domain.domain_context():
            with pytest.raises(IncorrectUsageError) as exc:
                domain.repository_for(domain.Cached)

        assert exc.value.code == "USAGE_CACHE_BACKED_NO_REPOSITORY"
        assert exc.value.location == "Domain.repository_for"

    def test_a_provider_backed_projection_gets_a_repository(self, domain):
        with domain.domain_context():
            assert domain.repository_for(Summary) is not None


# ---------------------------------------------------------------------------
# UNSUPPORTED_ELEMENT_CLASS
# ---------------------------------------------------------------------------
class TestUnsupportedElementClass:
    def test_a_plain_class_fires(self):
        d = Domain(name="Register")

        class NotAnElement:
            pass

        with pytest.raises(NotSupportedError) as exc:
            d.register(NotAnElement)

        assert exc.value.code == "UNSUPPORTED_ELEMENT_CLASS"
        assert exc.value.location == "Domain.register"

    def test_a_valid_element_registers(self):
        d = Domain(name="Register")
        d.register(Book)  # no raise
