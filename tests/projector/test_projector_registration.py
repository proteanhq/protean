import pytest

from protean.core.projection import _LegacyBaseProjection as BaseProjection
from protean.core.projector import BaseProjector
from protean.exceptions import IncorrectUsageError
from protean.utils import fully_qualified_name

from .elements import Token, TokenProjector, User


def test_registering_a_projector_manually(test_domain):
    try:
        test_domain.register(TokenProjector, projector_for=Token, aggregates=[User])
    except Exception:
        pytest.fail("Failed to register a Projector manually")

    assert fully_qualified_name(TokenProjector) in test_domain.registry.projectors


def test_registering_a_projector_via_annotation(test_domain):
    try:

        @test_domain.projector(projector_for=Token, aggregates=[User])
        class DuplicateProjector(BaseProjector):
            pass

    except Exception:
        pytest.fail("Failed to register a Projector via annotation")

    assert fully_qualified_name(DuplicateProjector) in test_domain.registry.projectors


def test_projection_has_to_be_registered_with_the_domain(test_domain):
    """
    Test that a projector has to be associated with a projection that is
    registered with and known to the domain.
    """

    class DummyProjection(BaseProjection):
        pass

    class DummyProjector(BaseProjector):
        pass

    # We don't register the projection with the domain, so it should fail
    test_domain.register(
        DummyProjector, projector_for=DummyProjection, aggregates=[User]
    )

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert exc.value.args[0] == (
        "`DummyProjection` is not a Projection, or is not registered in domain Test"
    )
