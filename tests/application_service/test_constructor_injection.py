"""An application service may take constructor arguments.

A production team on 0.16.3 kept plain orchestrators for 39 of 41 aggregates
because `@domain.application_service` appeared to forbid the constructor
injection their unit tests relied on (#1293). It never forbade it on purpose:
`__new__` forwarded its arguments to `object.__new__`, which accepts only the
class, so any service defining `__init__` died with

    TypeError: object.__new__() takes exactly one argument

a message naming neither the class nor `__init__`.
"""

from __future__ import annotations

import pytest

from protean.core.application_service import use_case
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.fields import String


@pytest.fixture
def domain(test_domain):
    @test_domain.aggregate
    class Order:
        reference = String()

    @test_domain.application_service(part_of=Order)
    class PlaceOrder:
        def __init__(self, gateway, notifier=None):
            self.gateway = gateway
            self.notifier = notifier

        @use_case
        def run(self):
            return f"placed via {self.gateway}"

    test_domain.init(traverse=False)
    test_domain.PlaceOrder = PlaceOrder
    return test_domain


class TestConstructorInjection:
    def test_a_positional_argument_reaches_the_instance(self, domain):
        assert domain.PlaceOrder("stripe").gateway == "stripe"

    def test_keyword_arguments_reach_the_instance(self, domain):
        service = domain.PlaceOrder(gateway="stripe", notifier="email")
        assert (service.gateway, service.notifier) == ("stripe", "email")

    def test_a_fake_can_be_injected_for_a_unit_test(self, domain):
        """The thing the team wanted: pass a double, no container required."""

        class FakeGateway:
            def charge(self, amount):
                return f"charged {amount}"

        service = domain.PlaceOrder(gateway=FakeGateway())
        assert service.gateway.charge(10) == "charged 10"

    def test_the_base_class_still_refuses_instantiation(self):
        from protean.core.application_service import BaseApplicationService

        with pytest.raises(NotSupportedError):
            BaseApplicationService()


@pytest.mark.no_test_domain
class TestUseCaseSaysWhatIsMissing:
    """`AttributeError: 'NoneType' object has no attribute 'providers'` was the
    old answer, raised from inside the transaction machinery, naming neither the
    use case nor the context.

    Marked `no_test_domain` because the autouse fixture activates a context, and
    the whole point here is what happens without one.
    """

    def _service(self):
        from protean import Domain

        domain = Domain(name="NoContext")

        @domain.aggregate
        class Order:
            reference = String()

        @domain.application_service(part_of=Order)
        class PlaceOrder:
            def __init__(self, gateway):
                self.gateway = gateway

            @use_case
            def run(self):
                return f"placed via {self.gateway}"

        domain.init(traverse=False)
        return domain, PlaceOrder

    def test_calling_outside_a_domain_context_names_the_use_case(self):
        _domain, service_cls = self._service()

        with pytest.raises(ConfigurationError) as exc:
            service_cls(gateway="stripe").run()

        message = str(exc.value)
        assert "PlaceOrder.run" in message
        assert "domain_context" in message

    def test_inside_a_context_it_just_runs(self):
        domain, service_cls = self._service()

        with domain.domain_context():
            assert service_cls(gateway="stripe").run() == "placed via stripe"

    def test_the_check_does_not_emit_the_no_domain_warning(self):
        """`current_domain` is a proxy: touching it with no context formats a
        full stack trace and warns. The guard reads the context stack instead."""
        import warnings

        _domain, service_cls = self._service()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(ConfigurationError):
                service_cls(gateway="stripe").run()

        assert not caught, (
            "checking for a context should not warn; "
            f"got {[str(w.message)[:60] for w in caught]}"
        )
