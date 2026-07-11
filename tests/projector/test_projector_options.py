import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.exceptions import IncorrectUsageError


class DummyAggregate1(BaseAggregate):
    pass


class DummyAggregate2(BaseAggregate):
    pass


class DummyProjector(BaseProjector):
    pass


class DummyProjection(BaseProjection):
    pass


class TestProjectorForOption:
    def test_projector_for_is_mandatory(self, test_domain):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(DummyProjector)

        assert (
            exc.value.args[0]
            == "Projector `DummyProjector` needs to be associated with a Projection"
        )

    def test_projector_for_specified_as_a_meta_attribute(self, test_domain):
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1", "dummy_stream_2"],
        )
        assert DummyProjector.meta_.projector_for == DummyProjection

    def test_part_of_defined_via_annotation(
        self,
        test_domain,
    ):
        @test_domain.projector(
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1", "dummy_stream_2"],
        )
        class DummyProjectorViaAnnotation(BaseProjector):
            pass

        assert DummyProjectorViaAnnotation.meta_.projector_for == DummyProjection


def test_projector_with_no_aggregates_or_stream_categories_raises_error(test_domain):
    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(DummyProjector, projector_for=DummyProjection)

    assert (
        exc.value.args[0]
        == "Projector `DummyProjector` needs to be associated with at least one Aggregate or Stream Category"
    )


class TestAggregatesOption:
    def test_aggregate_option_is_empty_list_by_default(self, test_domain):
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1", "dummy_stream_2"],
        )

        assert DummyProjector.meta_.aggregates == []

    def test_aggregate_as_option(self, test_domain):
        test_domain.register(DummyAggregate1)
        test_domain.register(
            DummyProjector, projector_for=DummyProjection, aggregates=[DummyAggregate1]
        )
        assert DummyProjector.meta_.aggregates == [DummyAggregate1]

    def test_multiple_aggregates_as_options(self, test_domain):
        test_domain.register(DummyAggregate1)
        test_domain.register(DummyAggregate2)
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            aggregates=[DummyAggregate1, DummyAggregate2],
        )
        assert DummyProjector.meta_.aggregates == [DummyAggregate1, DummyAggregate2]


class TestTransientRetryOptions:
    """Projectors accept the same transient-retry options as event and command
    handlers; the shared handler wrapper (``protean.utils.mixins``) consumes
    them."""

    def test_retry_options_default_to_none(self, test_domain):
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1"],
        )
        assert DummyProjector.meta_.retries is None
        assert DummyProjector.meta_.backoff is None
        assert DummyProjector.meta_.retry_exceptions is None

    def test_retry_options_are_accepted_and_stored(self, test_domain):
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1"],
            retries=8,
            backoff="exponential",
            retry_exceptions=["protean.exceptions.TransactionError"],
        )
        assert DummyProjector.meta_.retries == 8
        assert DummyProjector.meta_.backoff == "exponential"
        assert DummyProjector.meta_.retry_exceptions == [
            "protean.exceptions.TransactionError"
        ]

    def test_retry_options_via_annotation(self, test_domain):
        @test_domain.projector(
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1"],
            retries=3,
            backoff="linear",
        )
        class DummyProjectorWithRetry(BaseProjector):
            pass

        assert DummyProjectorWithRetry.meta_.retries == 3
        assert DummyProjectorWithRetry.meta_.backoff == "linear"


class TestStreamCategoriesOption:
    def test_stream_categories_as_option(self, test_domain):
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1", "dummy_stream_2"],
        )
        assert DummyProjector.meta_.stream_categories == [
            "dummy_stream_1",
            "dummy_stream_2",
        ]

    def test_stream_categories_derived_from_aggregates(self, test_domain):
        test_domain.register(DummyAggregate1)
        test_domain.register(DummyAggregate2)
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            aggregates=[DummyAggregate1, DummyAggregate2],
        )
        assert DummyProjector.meta_.stream_categories == [
            DummyAggregate1.meta_.stream_category,
            DummyAggregate2.meta_.stream_category,
        ]

    def test_explicit_stream_categories_overrides_aggregates_categories(
        self, test_domain
    ):
        test_domain.register(DummyAggregate1)
        test_domain.register(DummyAggregate2)
        test_domain.register(
            DummyProjector,
            projector_for=DummyProjection,
            stream_categories=["dummy_stream_1", "dummy_stream_2"],
            aggregates=[DummyAggregate1, DummyAggregate2],
        )
        assert DummyProjector.meta_.stream_categories == [
            "dummy_stream_1",
            "dummy_stream_2",
        ]
