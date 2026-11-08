import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.event_sourced_repository import BaseEventSourcedRepository
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.domain import Domain
from protean.domain.routing import MessageRouter
from protean.exceptions import ConfigurationError
from protean.fields import DateTime, Identifier, String
from protean.utils.mixins import handle


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


class Email(BaseAggregate):
    email = String()
    sent_at = DateTime()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Activated(BaseEvent):
    id = Identifier()
    activated_at = DateTime()


class Sent(BaseEvent):
    email = String()
    sent_at = DateTime()


class Register(BaseCommand):
    id = Identifier()
    email = String()


class Activate(BaseCommand):
    id = Identifier()


class UnknownCommand(BaseCommand):
    foo = String()


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_activation_email(self, event: Registered) -> None:
        pass

    @handle(Activated)
    def provision_user(self, event: Activated) -> None:
        pass


class EmailEventHandler(BaseEventHandler):
    @handle(Sent)
    def record_sent_email(self, event: Sent) -> None:
        pass


class UserMetrics(BaseEventHandler):
    @handle(Registered)
    def count_registrations(self, event: Registered) -> None:
        pass


class AllEventsHandler(BaseEventHandler):
    @handle("$any")
    def universal_handler(self, event: BaseEvent) -> None:
        pass


class UserAuditHandler(BaseEventHandler):
    @handle("$any")
    def audit(self, event: BaseEvent) -> None:
        pass


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        pass


class UserReport(BaseProjection):
    id = Identifier(identifier=True)
    email = String()


class EmailReport(BaseProjection):
    id = Identifier(identifier=True)
    email = String()


class UserReportProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered) -> None:
        pass


class OnboardingPM(BaseProcessManager):
    user_id = Identifier()

    @handle(Registered, start=True, correlate="id")
    def on_registered(self, event: Registered) -> None:
        self.user_id = event.id


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Activate, part_of=User)
    test_domain.register(Email, event_sourced=True)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(EmailEventHandler, part_of=Email)
    test_domain.register(UserCommandHandler, part_of=User)


class TestEventRouting:
    def test_internal_events_route_to_their_stream_handlers(self, test_domain):
        test_domain.init(traverse=False)

        router = test_domain._router
        assert router.handlers_for(Registered()) == {UserEventHandler}
        assert router.handlers_for(Sent()) == {EmailEventHandler}

    def test_all_stream_handler_is_returned_for_every_internal_event(self, test_domain):
        test_domain.register(AllEventsHandler, stream_category="$all")
        test_domain.init(traverse=False)

        router = test_domain._router
        assert router.handlers_for(Registered()) == {
            UserEventHandler,
            AllEventsHandler,
        }
        assert router.handlers_for(Sent()) == {EmailEventHandler, AllEventsHandler}

    def test_part_of_any_handler_stays_on_its_aggregate_stream(self, test_domain):
        test_domain.register(UserAuditHandler, part_of=User)
        test_domain.init(traverse=False)

        router = test_domain._router
        assert router.handlers_for(Activated()) == {UserEventHandler, UserAuditHandler}
        assert router.handlers_for(Sent()) == {EmailEventHandler}

    def test_external_event_routes_by_type_plus_all_stream(self, test_domain):
        class ExternalRegistered(BaseEvent):
            foo = String()

        class ExternalHandler(BaseEventHandler):
            @handle(ExternalRegistered)
            def on_external(self, event: ExternalRegistered) -> None:
                pass

        test_domain.register_external_event(
            ExternalRegistered, "Bar.ExternalRegistered.v1"
        )
        test_domain.register(ExternalHandler, part_of=Email)
        test_domain.register(AllEventsHandler, stream_category="$all")
        test_domain.register(UserAuditHandler, part_of=User)
        test_domain.init(traverse=False)

        assert test_domain._router.handlers_for(ExternalRegistered(foo="x")) == {
            ExternalHandler,
            AllEventsHandler,
        }

    def test_process_manager_routes_on_its_stream_categories(self, test_domain):
        test_domain.register(OnboardingPM, stream_categories=["test::user"])
        test_domain.init(traverse=False)

        router = test_domain._router
        assert router.handlers_for(Registered()) == {UserEventHandler, OnboardingPM}
        assert OnboardingPM not in router.handlers_for(Sent())

    def test_domain_handlers_for_reads_the_router(self, test_domain):
        test_domain.register(UserMetrics, part_of=User)
        test_domain.init(traverse=False)

        assert test_domain.handlers_for(Registered()) == {
            UserEventHandler,
            UserMetrics,
        }


class TestProjectorRouting:
    def test_projectors_for_returns_the_projection_projector(self, test_domain):
        test_domain.register(UserReport)
        test_domain.register(EmailReport)
        test_domain.register(
            UserReportProjector, projector_for=UserReport, aggregates=[User]
        )
        test_domain.init(traverse=False)

        assert test_domain._router.projectors_for(UserReport) == {UserReportProjector}
        assert test_domain.projectors_for(UserReport) == {UserReportProjector}
        assert test_domain._router.projectors_for(EmailReport) == set()
        assert UserReportProjector in test_domain.handlers_for(Registered())


class TestCommandRouting:
    def test_command_routes_to_its_handler(self, test_domain):
        test_domain.init(traverse=False)

        assert test_domain._router.command_handler_for(Register()) is UserCommandHandler
        assert test_domain.command_handler_for(Register()) is UserCommandHandler

    def test_command_without_a_handler_method_returns_none(self, test_domain):
        test_domain.init(traverse=False)

        assert test_domain._router.command_handler_for(Activate()) is None

    def test_command_without_part_of_raises(self, test_domain):
        test_domain.init(traverse=False)

        with pytest.raises(ConfigurationError) as exc:
            test_domain._router.command_handler_for(UnknownCommand)

        assert exc.value.args[0] == (
            "Command `UnknownCommand` needs to be associated with an aggregate"
        )


class TestEmptyRouter:
    def test_router_without_registry_has_no_routes(self, test_domain):
        router = MessageRouter()

        assert router.handlers_for(Registered()) == set()
        assert router.projectors_for(UserReport) == set()
        assert router.command_handler_for(Register()) is None

    def test_domain_before_init_has_no_routes(self, test_domain):
        # A separate domain with routable elements registered and no `init()`.
        domain = Domain(name="Uninitialized")
        domain.register(User, event_sourced=True)
        domain.register(Registered, part_of=User)
        domain.register(Register, part_of=User)
        domain.register(UserEventHandler, part_of=User)
        domain.register(UserCommandHandler, part_of=User)

        assert domain._router.handlers_for(Registered()) == set()
        assert domain._router.command_handler_for(Register()) is None


class TestReinitialization:
    def test_reinit_builds_a_fresh_router(self, test_domain):
        test_domain.init(traverse=False)
        before = test_domain._router
        assert before.handlers_for(Registered()) == {UserEventHandler}

        test_domain.register(UserMetrics, part_of=User)
        test_domain.init(traverse=False)

        after = test_domain._router
        assert after is not before
        assert after.handlers_for(Registered()) == {UserEventHandler, UserMetrics}
        # The old router was not changed in place.
        assert before.handlers_for(Registered()) == {UserEventHandler}


class TestEventSourcedRepository:
    def test_repository_for_event_sourced_aggregate(self, test_domain):
        test_domain.init(traverse=False)

        repository = test_domain.repository_for(User)
        assert isinstance(repository, BaseEventSourcedRepository)
        assert repository.meta_.part_of is User

        direct = test_domain._event_sourced_repository_for(Email)
        assert isinstance(direct, BaseEventSourcedRepository)
        assert direct.meta_.part_of is Email


class TestEventStoreHoldsNoRouting:
    @pytest.mark.parametrize(
        "name",
        [
            "handlers_for",
            "projectors_for",
            "command_handler_for",
            "repository_for",
            "_initialize_event_streams",
            "_initialize_command_streams",
            "_event_streams",
            "_command_streams",
            "_projectors",
        ],
    )
    def test_event_store_has_no_routing_attribute(self, test_domain, name):
        test_domain.init(traverse=False)

        assert not hasattr(test_domain.event_store, name)
