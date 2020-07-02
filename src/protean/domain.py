"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""
# Standard Library Imports
import importlib
import logging
import sys

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

# Protean
import marshmallow

from protean.core.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ObjectNotFoundError,
)
from protean.globals import current_uow
from protean.utils import fully_qualified_name
from werkzeug.datastructures import ImmutableDict

# Local/Relative Imports
from .config import Config, ConfigAttribute
from .context import DomainContext, _DomainContextGlobals
from .helpers import _PackageBoundObject, get_debug_flag, get_env

logger = logging.getLogger("protean.domain")

# a singleton sentinel value for parameter defaults
_sentinel = object()


class DomainObjects(Enum):
    AGGREGATE = "AGGREGATE"
    APPLICATION_SERVICE = "APPLICATION_SERVICE"
    COMMAND = "COMMAND"
    COMMAND_HANDLER = "COMMAND_HANDLER"
    DOMAIN_EVENT = "DOMAIN_EVENT"
    DOMAIN_SERVICE = "DOMAIN_SERVICE"
    EMAIL = "EMAIL"
    ENTITY = "ENTITY"
    MODEL = "MODEL"
    REPOSITORY = "REPOSITORY"
    SERIALIZER = "SERIALIZER"
    SUBSCRIBER = "SUBSCRIBER"
    VALUE_OBJECT = "VALUE_OBJECT"


@dataclass
class _DomainRegistry:
    _elements: Dict[str, dict] = field(default_factory=dict)

    @dataclass
    class DomainRecord:
        name: str
        qualname: str
        class_type: str
        cls: Any

    def __post_init__(self):
        """Initialize placeholders for element types"""
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)

    def register_element(self, element_cls):
        if element_cls.element_type.name not in DomainObjects.__members__:
            raise NotImplementedError

        element_name = fully_qualified_name(element_cls)

        element = self._elements[element_cls.element_type.value][element_name]
        if element:
            # raise ConfigurationError(f'Element {element_name} has already been registered')
            logger.debug(f"Element {element_name} was already in the registry")
        else:
            element_record = _DomainRegistry.DomainRecord(
                name=element_cls.__name__,
                qualname=element_name,
                class_type=element_cls.element_type.value,
                cls=element_cls,
            )

            self._elements[element_cls.element_type.value][
                element_name
            ] = element_record

            logger.debug(
                f"Registered Element {element_name} with Domain as a {element_cls.element_type.value}"
            )

    def delist_element(self, element_cls):
        if element_cls.element_type.name not in DomainObjects.__members__:
            raise NotImplementedError

        element_name = fully_qualified_name(element_cls)

        self._elements[element_cls.element_type.value].pop(element_name, None)


class Domain(_PackageBoundObject):
    """The domain object is a one-stop gateway to:
    * Registering Domain Objects/Concepts
    * Querying/Retrieving Domain Artifacts like Entities, Services, etc.
    * Retrieve injected infrastructure adapters

    Usually you create a :class:`Domain` instance in your main module or
    in the :file:`__init__.py` file of your package like this::

        from protean import Domain
        domain = Domain(__name__)

    :param domain_name: the name of the domain
    """

    from protean.core.aggregate import BaseAggregate
    from protean.core.application_service import BaseApplicationService
    from protean.core.broker.subscriber import BaseSubscriber
    from protean.core.command import BaseCommand
    from protean.core.command_handler import BaseCommandHandler
    from protean.core.domain_event import BaseDomainEvent
    from protean.core.domain_service import BaseDomainService
    from protean.core.email import BaseEmail
    from protean.core.entity import BaseEntity
    from protean.core.repository.model import BaseModel
    from protean.core.repository.base import BaseRepository
    from protean.core.serializer import BaseSerializer
    from protean.core.value_object import BaseValueObject
    from protean.utils import IdentityStrategy, IdentityType

    config_class = Config
    domain_context_globals_class = _DomainContextGlobals

    #: What environment the app is running in Protean and extensions may
    #: enable behaviors based on the environment, such as enabling debug
    #: mode. This maps to the :data:`ENV` config key. This is set by the
    #: :envvar:`PROTEAN_ENV` environment variable and may not behave as
    #: expected if set in code.
    #:
    #: **Do not enable development when deploying in production.**
    #:
    #: Default: ``'production'``
    env = ConfigAttribute("ENV")

    #: The testing flag.  Set this to ``True`` to enable the test mode of
    #: Protean extensions (and in the future probably also Protean itself).
    #: For example this might activate test helpers that have an
    #: additional runtime cost which should not be enabled by default.
    #:
    #: This attribute can also be configured from the config with the
    #: ``TESTING`` configuration key.  Defaults to ``False``.
    testing = ConfigAttribute("TESTING")

    #: If a secret key is set, cryptographic components can use this to
    #: sign cookies and other things. Set this to a complex random value
    #: when you want to use the secure cookie for instance.
    #:
    #: This attribute can also be configured from the config with the
    #: :data:`SECRET_KEY` configuration key. Defaults to ``None``.
    secret_key = ConfigAttribute("SECRET_KEY")

    root_path = None

    default_config = ImmutableDict(
        {
            "ENV": None,
            "DEBUG": None,
            "SECRET_KEY": None,
            "AUTOLOAD_DOMAIN": True,
            "IDENTITY_STRATEGY": IdentityStrategy.UUID,
            "IDENTITY_TYPE": IdentityType.STRING,
            "DATABASES": {
                "default": {
                    "PROVIDER": "protean.impl.repository.dict_repo.DictProvider",
                },
            },
            "BROKERS": {
                "default": {
                    "PROVIDER": "protean.impl.broker.memory_broker.MemoryBroker",
                },
            },
            "EMAIL_PROVIDERS": {
                "default": {
                    "PROVIDER": "protean.impl.email.dummy.DummyEmailProvider",
                    "DEFAULT_FROM_EMAIL": "admin@team8solutions.com",
                },
            },
            "AGGREGATE_CHILDREN_LIMIT": 100,
        },
    )

    base_class_mapping = {
        DomainObjects.AGGREGATE.value: BaseAggregate,
        DomainObjects.APPLICATION_SERVICE.value: BaseApplicationService,
        DomainObjects.COMMAND.value: BaseCommand,
        DomainObjects.COMMAND_HANDLER.value: BaseCommandHandler,
        DomainObjects.DOMAIN_EVENT.value: BaseDomainEvent,
        DomainObjects.DOMAIN_SERVICE.value: BaseDomainService,
        DomainObjects.ENTITY.value: BaseEntity,
        DomainObjects.EMAIL.value: BaseEmail,
        DomainObjects.MODEL.value: BaseModel,
        DomainObjects.REPOSITORY.value: BaseRepository,
        DomainObjects.SERIALIZER.value: marshmallow.Schema,
        DomainObjects.SUBSCRIBER.value: BaseSubscriber,
        DomainObjects.VALUE_OBJECT.value: BaseValueObject,
    }

    def __init__(
        self, domain_name=__name__, root_path=None, instance_relative_config=False
    ):

        _PackageBoundObject.__init__(
            self, domain_name, root_path=root_path,
        )

        self.domain_name = domain_name

        # Registry for all domain Objects
        self._domain_registry = _DomainRegistry()

        #: The configuration dictionary as :class:`Config`.  This behaves
        #: exactly like a regular dictionary but supports additional methods
        #: to load a config from files.
        self.config = self.make_config(instance_relative_config)

        self.providers = None
        self._brokers = None
        self._email_providers = None

        # Cache for holding Model to Entity/Aggregate associations
        self._models = {}
        self._constructed_models = {}

        #: A list of functions that are called when the domain context
        #: is destroyed.  This is the place to store code that cleans up and
        #: disconnects from databases, for example.
        self.teardown_domain_context_functions = []

    def init(self):
        """ Parse the domain folder, and attach elements dynamically to the domain.

        Protean parses all files in the domain file's folder, as well as under it,
        to load elements. So, all domain files are to be nested under the file contain
        the domain definition.

        One can use the `AUTOLOAD_DOMAIN` flag in Protean config, `True` by default,
        to control this functionality.

        When enabled, Protean is responsible for loading domain elements and ensuring
        all functionality is activated.

        The developer is responsible for activating functionality manually when
        autoloading is disabled. Element activation can be done by importing them
        in central areas of domain execution, like Application Services.

        For example, asynchronous aspects of a domain like its Subscribers and
        Event Handlers should be imported in their relevant Application Services
        and Aggregates.

        This method bubbles up circular import issues, if present, in the domain code.
        """
        if self.config["AUTOLOAD_DOMAIN"] is True:
            import importlib.util
            import inspect
            import os
            import pathlib

            # Fetch the domain file and derive the system path
            domain_path = inspect.stack()[1][
                1
            ]  # Find the file in which the domain is defined
            dir_name = pathlib.PurePath(pathlib.Path(domain_path).resolve()).parent
            path = pathlib.Path(dir_name)  # Resolve the domain file's directory
            system_folder_path = (
                path.parent
            )  # Get the directory of the domain file to traverse from

            logger.debug(f"Loading domain from {dir_name}...")

            for root, dirs, files in os.walk(dir_name):
                if pathlib.PurePath(root).name not in ["__pycache__"]:
                    package_path = root[len(str(system_folder_path)) + 1 :]
                    module_name = package_path.replace(os.sep, ".")

                    for file in files:
                        file_base_name = os.path.basename(file)

                        # Construct the module path to import from
                        if file_base_name != "__init__":
                            sub_module_name = os.path.splitext(file_base_name)[0]
                            file_module_name = module_name + "." + sub_module_name
                        else:
                            file_module_name = module_name
                        full_file_path = os.path.join(root, file)

                        try:
                            if (
                                full_file_path != domain_path
                            ):  # Don't load the domain file itself again
                                spec = importlib.util.spec_from_file_location(
                                    file_module_name, full_file_path
                                )
                                module = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(module)

                                logger.debug(f"Loaded {file_module_name}")
                        except ModuleNotFoundError as exc:
                            logger.error(f"Error while loading a module: {exc}")
                        except ModuleNotFoundError as exc:
                            logger.error(f"Error while autoloading modules: {exc}")

    def make_config(self, instance_relative=False):
        """Used to create the config attribute by the Domain constructor.
        The `instance_relative` parameter is passed in from the constructor
        of Domain (there named `instance_relative_config`) and indicates if
        the config should be relative to the instance path or the root path
        of the application.
        """
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        defaults = dict(self.default_config)
        defaults["ENV"] = get_env()
        defaults["DEBUG"] = get_debug_flag()
        return self.config_class(root_path, defaults)

    def domain_context(self):
        """Create an :class:`~protean.context.DomainContext`. Use as a ``with``
        block to push the context, which will make :data:`current_domain`
        point at this domain.

        ::

            with domain.domain_context():
                init_db()
        """
        return DomainContext(self)

    def teardown_domain_context(self, f):
        """Registers a function to be called when the domain context
        ends.

        Example::

            ctx = domain.domain_context()
            ctx.push()
            ...
            ctx.pop()

        When ``ctx.pop()`` is executed in the above example, the teardown
        functions are called just before the domain context moves from the
        stack of active contexts.  This becomes relevant if you are using
        such constructs in tests.

        When a teardown function was called because of an unhandled exception
        it will be passed an error object. If an :meth:`errorhandler` is
        registered, it will handle the exception and the teardown will not
        receive it.

        The return values of teardown functions are ignored.
        """
        self.teardown_domain_context_functions.append(f)
        return f

    def do_teardown_domain_context(self, exc=_sentinel):
        """Called right before the domain context is popped.

        This calls all functions decorated with
        :meth:`teardown_domain_context`.

        This is called by
        :meth:`DomainContext.pop() <protean.context.DomainContext.pop>`.
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        for func in reversed(self.teardown_domain_context_functions):
            func(exc)

    @property
    def registry(self):
        return self._domain_registry

    @property
    def aggregates(self):
        return self._domain_registry._elements[DomainObjects.AGGREGATE.value]

    @property
    def application_services(self):
        return self._domain_registry._elements[DomainObjects.APPLICATION_SERVICE.value]

    @property
    def commands(self):
        return self._domain_registry._elements[DomainObjects.COMMAND.value]

    @property
    def command_handlers(self):
        return self._domain_registry._elements[DomainObjects.COMMAND_HANDLER.value]

    @property
    def domain_events(self):
        return self._domain_registry._elements[DomainObjects.DOMAIN_EVENT.value]

    @property
    def domain_services(self):
        return self._domain_registry._elements[DomainObjects.DOMAIN_SERVICE.value]

    @property
    def emails(self):
        return self._domain_registry._elements[DomainObjects.EMAIL.value]

    @property
    def models(self):
        return self._domain_registry._elements[DomainObjects.MODEL.value]

    @property
    def entities(self):
        return self._domain_registry._elements[DomainObjects.ENTITY.value]

    @property
    def repositories(self):
        return self._domain_registry._elements[DomainObjects.REPOSITORY.value]

    @property
    def serializers(self):
        return self._domain_registry._elements[DomainObjects.SERIALIZER.value]

    @property
    def subscribers(self):
        return self._domain_registry._elements[DomainObjects.SUBSCRIBER.value]

    @property
    def value_objects(self):
        return self._domain_registry._elements[DomainObjects.VALUE_OBJECT.value]

    def _register_element(self, element_type, element_cls, **kwargs):  # noqa: C901
        """Register class into the domain"""
        # Check if `element_cls` is already a subclass of the Element Type
        #   which would be the case in an explicit declaration like `class Account(BaseEntity):`
        #
        # We will need to construct a class derived from the right base class
        #   if the Element was specified through annotation, like so:
        #
        #  ```
        #       @Entity
        #       class Account:
        #  ```

        if element_type == DomainObjects.VALUE_OBJECT:
            from protean.core.value_object import ValueObjectFactory

            new_cls = ValueObjectFactory.prep_class(element_cls, **kwargs)
        elif element_type == DomainObjects.REPOSITORY:
            from protean.core.repository.base import RepositoryFactory

            new_cls = RepositoryFactory.prep_class(element_cls, **kwargs)
        elif element_type == DomainObjects.AGGREGATE:
            from protean.core.aggregate import AggregateFactory

            new_cls = AggregateFactory.prep_class(element_cls, **kwargs)
        elif element_type == DomainObjects.ENTITY:
            from protean.core.entity import EntityFactory

            new_cls = EntityFactory.prep_class(element_cls, **kwargs)
        elif element_type == DomainObjects.SUBSCRIBER:
            from protean.core.broker.subscriber import SubscriberFactory

            new_cls = SubscriberFactory.prep_class(element_cls, **kwargs)
        elif element_type == DomainObjects.DOMAIN_EVENT:
            from protean.core.domain_event import DomainEventFactory

            new_cls = DomainEventFactory.prep_class(element_cls, **kwargs)
        else:
            try:
                if not issubclass(
                    element_cls, self.base_class_mapping[element_type.value]
                ):
                    new_dict = element_cls.__dict__.copy()
                    new_dict.pop(
                        "__dict__", None
                    )  # Remove __dict__ to prevent recursion

                    # Hack to switch between `marshmallow.Schema` and `BaseSerializer`
                    #   while creating the derived class for Serializers
                    #
                    # This becomes necessary because we need to derive the undecorated class
                    #   from `BaseSerializer`, but once derived, the base hierarchy only reflects
                    #   `marshmallow.Schema` (This is a metaclass, so it disrupts hierarchy).
                    if element_type == DomainObjects.SERIALIZER:
                        from protean.core.serializer import BaseSerializer

                        base_cls = BaseSerializer
                    else:
                        base_cls = self.base_class_mapping[element_type.value]

                    new_cls = type(element_cls.__name__, (base_cls,), new_dict)
                else:
                    new_cls = element_cls  # Element was already subclassed properly
            except BaseException as exc:
                logger.debug("Error during Element registration:", repr(exc))
                raise IncorrectUsageError(
                    "Invalid class {element_cls.__name__} for type {element_type.value}"
                    " (Error: {exc})",
                )

            aggregate_cls = None

            if element_type == DomainObjects.MODEL and self._validate_model_class(
                new_cls
            ):
                # Associate aggregate/entity class with model if `entity_cls` was supplied as an explicit parameter
                from protean.core.repository.model import ModelMeta

                if hasattr(new_cls, "Meta"):
                    new_cls.meta_ = ModelMeta(new_cls.Meta)
                else:
                    new_cls.meta_ = ModelMeta()

                entity_cls = new_cls.meta_.entity_cls or kwargs.pop("entity_cls", None)
                if not entity_cls:
                    raise IncorrectUsageError(
                        "Models need to be associated with an Entity or Aggregate"
                    )

                if not new_cls.meta_.entity_cls:
                    new_cls.meta_.entity_cls = entity_cls

                # Remember model association with aggregate/entity class, for easy fetching
                self._models[fully_qualified_name(entity_cls)] = new_cls

            if (
                element_type == DomainObjects.COMMAND_HANDLER
                and self._validate_command_handler_class(new_cls)
            ):
                command_cls = new_cls.meta_.command_cls or kwargs.pop("command", None)
                broker_name = new_cls.meta_.broker or "default"
                if not command_cls:
                    raise IncorrectUsageError(
                        "Command Handlers need to be associated with a Command"
                    )

                new_cls.meta_.command_cls = command_cls
                new_cls.meta_.broker = broker_name

            if element_type == DomainObjects.EMAIL and self._validate_email_class(
                new_cls
            ):
                provider_name = new_cls.meta_.provider or "default"
                new_cls.meta_.provider = provider_name

            # Enrich element with domain information
            if hasattr(new_cls, "meta_"):
                new_cls.meta_.aggregate_cls = aggregate_cls or kwargs.pop(
                    "aggregate_cls", None
                )
                new_cls.meta_.bounded_context = kwargs.pop("bounded_context", None)

        # Register element with domain
        self._domain_registry.register_element(new_cls)

        return new_cls

    def _validate_model_class(self, element_cls):
        # Import here to avoid cyclic dependency
        from protean.core.repository.model import BaseModel

        if not issubclass(element_cls, BaseModel):
            raise AssertionError(
                f"Element {element_cls.__name__} must be subclass of `BaseModel`"
            )

        return True

    def _validate_serializer_class(self, element_cls):
        # Import here to avoid cyclic dependency
        from protean.core.serializer import BaseSerializer

        if not issubclass(element_cls, BaseSerializer):
            raise AssertionError(
                f"Element {element_cls.__name__} must be subclass of `BaseSerializer`"
            )

        return True

    def _validate_command_handler_class(self, element_cls):
        # Import here to avoid cyclic dependency
        from protean.core.command_handler import BaseCommandHandler

        if not issubclass(element_cls, BaseCommandHandler):
            raise AssertionError(
                f"Element {element_cls.__name__} must be subclass of `BaseCommandHandler`"
            )

        return True

    def _validate_email_class(self, element_cls):
        # Import here to avoid cyclic dependency
        from protean.core.email import BaseEmail

        if not issubclass(element_cls, BaseEmail):
            raise AssertionError(
                f"Element {element_cls.__name__} must be subclass of `BaseEmail`"
            )

        return True

    # _cls should never be specified by keyword, so start it with an
    # underscore.  The presence of _cls is used to detect if this
    # decorator is being called with parameters or not.
    def _domain_element(
        self,
        element_type,
        _cls=None,
        *,
        aggregate_cls=None,
        bounded_context=None,
        domain_event=None,
        command=None,
        entity_cls=None,
        provider=None,
        model=None,
    ):
        """Returns the registered class after decoarating it and recording its presence in the domain"""

        def wrap(cls):
            return self._register_element(
                element_type,
                cls,
                aggregate_cls=aggregate_cls,
                bounded_context=bounded_context,
                domain_event=domain_event,
                command=command,
                entity_cls=entity_cls,
                provider=provider,
                model=model,
            )

        # See if we're being called as @Entity or @Entity().
        if _cls is None:
            # We're called with parens.
            return wrap

        # We're called as @dataclass without parens.
        return wrap(_cls)

    def aggregate(self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.AGGREGATE,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def application_service(
        self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs
    ):
        return self._domain_element(
            DomainObjects.APPLICATION_SERVICE,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def command(self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.COMMAND,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def command_handler(
        self, command, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs
    ):
        return self._domain_element(
            DomainObjects.COMMAND_HANDLER,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
            command=command,
        )

    def domain_event(
        self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs
    ):
        return self._domain_element(
            DomainObjects.DOMAIN_EVENT,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def domain_service(
        self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs
    ):
        return self._domain_element(
            DomainObjects.DOMAIN_SERVICE,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def entity(self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.ENTITY,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def email(self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.EMAIL,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def model(self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.MODEL,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def repository(self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.REPOSITORY,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def serializer(self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.SERIALIZER,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def subscriber(
        self,
        domain_event,
        _cls=None,
        aggregate_cls=None,
        bounded_context=None,
        **kwargs,
    ):
        return self._domain_element(
            DomainObjects.SUBSCRIBER,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
            domain_event=domain_event,
        )

    def value_object(
        self, _cls=None, aggregate_cls=None, bounded_context=None, **kwargs
    ):
        return self._domain_element(
            DomainObjects.VALUE_OBJECT,
            _cls=_cls,
            **kwargs,
            aggregate_cls=aggregate_cls,
            bounded_context=bounded_context,
        )

    def register_model(self, model_cls, **kwargs):
        """Register a model class"""
        return self._register_element(DomainObjects.MODEL, model_cls, **kwargs)

    def register(self, element_cls, **kwargs):
        """Register an element already subclassed with the correct Hierarchy"""
        if getattr(element_cls, "element_type", None) not in [
            element for element in DomainObjects
        ]:
            raise NotImplementedError

        if (
            hasattr(element_cls, "meta_")
            and hasattr(element_cls.meta_, "abstract")
            and element_cls.meta_.abstract is True
        ):
            raise NotSupportedError(
                f"{element_cls.__name__} class has been marked abstract"
                " and cannot be instantiated"
            )

        return self._register_element(element_cls.element_type, element_cls, **kwargs)

    def delist(self, element_cls):
        """Delist a Domain Element.

        This method will result in a no-op if the entity class was not found
        in the registry for whatever reason.
        """
        if getattr(element_cls, "element_type", None) not in [
            element for element in DomainObjects
        ]:
            raise NotImplementedError

        self._domain_registry.dei_element(element_cls.element_type, element_cls)

    def _get_element_by_name(self, element_types, element_name):
        """Fetch Domain record with an Element name"""
        for element_type in element_types:
            if element_name in self._domain_registry._elements[element_type.value]:
                return self._domain_registry._elements[element_type.value][element_name]
        else:
            raise ObjectNotFoundError(
                f"Element {element_name} not registered in domain {self.domain_name}"
            )

    def _get_element_by_class(self, element_types, element_cls):
        """Fetch Domain record with Element class details"""
        element_qualname = fully_qualified_name(element_cls)
        return self._get_element_by_name(element_types, element_qualname)

    def _replace_element_by_class(self, new_element_cls):
        aggregate_record = self._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY), new_element_cls
        )

        self._domain_registry._elements[aggregate_record.class_type][
            aggregate_record.qualname
        ].cls = new_element_cls

    def get_model(self, aggregate_cls):
        """Retrieve Model class connected to Entity"""
        # Return model if already constructed
        if fully_qualified_name(aggregate_cls) in self._constructed_models:
            return self._constructed_models[fully_qualified_name(aggregate_cls)]

        # Fixate on the provider associated with the aggregate class
        aggregate_record = self._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY), aggregate_cls
        )
        provider = self.get_provider(aggregate_record.cls.meta_.provider)

        # If a model was associated with the aggregate record, give it a higher priority
        #   and do not bake a new model class from aggregate/entity attributes
        custom_model_cls = None
        if fully_qualified_name(aggregate_cls) in self._models:
            custom_model_cls = self._models[fully_qualified_name(aggregate_cls)]

        if custom_model_cls:
            # Get the decorated model class.
            #   This is a no-op if the provider decides that the model is fully-baked
            model_cls = provider.decorate_model_class(
                aggregate_record.cls, custom_model_cls
            )
        else:
            # No model was associated with the aggregate/entity explicitly.
            #   So ask the Provider to bake a new model, initialized properly for this aggregate
            #   and return it
            model_cls = provider.construct_model_class(aggregate_record.cls)

        self._constructed_models[fully_qualified_name(aggregate_cls)] = model_cls
        return model_cls

    def _initialize_providers(self):
        """Read config file and initialize providers"""
        configured_providers = self.config["DATABASES"]
        provider_objects = {}

        if configured_providers and isinstance(configured_providers, dict):
            if "default" not in configured_providers:
                raise ConfigurationError("You must define a 'default' provider")

            for provider_name, conn_info in configured_providers.items():
                provider_full_path = conn_info["PROVIDER"]
                provider_module, provider_class = provider_full_path.rsplit(
                    ".", maxsplit=1
                )

                provider_cls = getattr(
                    importlib.import_module(provider_module), provider_class
                )
                provider_objects[provider_name] = provider_cls(
                    provider_name, self, conn_info
                )

        return provider_objects

    def has_provider(self, provider_name):
        if self.providers is None:
            self.providers = self._initialize_providers()

        return provider_name in self.providers

    def get_provider(self, provider_name):
        """Retrieve the provider object with a given provider name"""
        if self.providers is None:
            self.providers = self._initialize_providers()

        try:
            return self.providers[provider_name]
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def get_connection(self, provider_name="default"):
        """Fetch connection from Provider"""
        if self.providers is None:
            self.providers = self._initialize_providers()

        try:
            return self.providers[provider_name].get_connection()
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def providers_list(self):
        """A generator that helps users iterator through providers"""
        if self.providers is None:
            self.providers = self._initialize_providers()

        for provider_name in self.providers:
            yield self.providers[provider_name]

    def repository_for(self, aggregate_cls):
        """Retrieve a Repository registered for the Aggregate"""
        from protean.core.aggregate import BaseAggregate

        if not issubclass(aggregate_cls, BaseAggregate):
            raise AssertionError(
                f"Element {aggregate_cls.__name__} must be subclass of `BaseAggregate`"
            )

        try:
            repository_record = next(
                repository
                for _, repository in self.repositories.items()
                if repository.cls.meta_.aggregate_cls.__name__ == aggregate_cls.__name__
            )
        except StopIteration:
            logger.debug(f"Constructing a Repository for {aggregate_cls}...")

            from protean.core.repository.base import BaseRepository

            new_class = type(
                aggregate_cls.__name__ + "Repository", (BaseRepository,), {}
            )

            self._domain_element(
                DomainObjects.REPOSITORY,
                _cls=new_class,
                aggregate_cls=aggregate_cls,
                bounded_context=aggregate_cls.meta_.bounded_context,
            )

            # FIXME Avoid comparing classes / Fetch a Repository class directly by its aggregate class
            repository_record = next(
                repository
                for _, repository in self.repositories.items()
                if repository.cls.meta_.aggregate_cls.__name__ == aggregate_cls.__name__
            )

        return repository_record.cls()

    def get_dao(self, aggregate_cls):
        """Retrieve a DAO registered for the Aggregate with a live connection"""
        # Fixate on the provider associated with the aggregate class
        aggregate_record = self._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY), aggregate_cls
        )
        provider = self.get_provider(aggregate_record.cls.meta_.provider)

        # Fixate on Model class at the domain level because an explicit model may have been registered
        model_cls = self.get_model(aggregate_record.cls)

        return provider.get_dao(aggregate_record.cls, model_cls)

    def _initialize_brokers(self):
        """Read config file and initialize brokers"""
        configured_brokers = self.config["BROKERS"]
        broker_objects = {}

        logger.debug("Initializing brokers...")
        if configured_brokers and isinstance(configured_brokers, dict):
            if "default" not in configured_brokers:
                raise ConfigurationError("You must define a 'default' broker")

            for broker_name, conn_info in configured_brokers.items():
                broker_full_path = conn_info["PROVIDER"]
                broker_module, broker_class = broker_full_path.rsplit(".", maxsplit=1)

                broker_cls = getattr(
                    importlib.import_module(broker_module), broker_class
                )
                broker_objects[broker_name] = broker_cls(broker_name, self, conn_info)

        self._brokers = broker_objects

        # Initialize subscribers for Brokers
        for _, subscriber_record in self.subscribers.items():
            subscriber = subscriber_record.cls
            broker_name = subscriber.meta_.broker

            if broker_name not in self._brokers:
                raise ConfigurationError(
                    f"Broker {broker_name} has not been configured."
                )

            self._brokers[broker_name].register(
                subscriber.meta_.domain_event, subscriber
            )

        # Initialize command handlers for Brokers
        for _, command_handler_record in self.command_handlers.items():
            command_handler = command_handler_record.cls
            broker_name = command_handler.meta_.broker

            if broker_name not in self._brokers:
                raise ConfigurationError(
                    f"Broker {broker_name} has not been configured."
                )

            self._brokers[broker_name].register(
                command_handler.meta_.command_cls, command_handler
            )

    def has_broker(self, broker_name):
        if self._brokers is None:
            self._initialize_brokers()

        return broker_name in self._brokers

    def get_broker(self, broker_name):
        """Retrieve the broker object with a given broker name"""
        if self._brokers is None:
            self._initialize_brokers()

        try:
            return self._brokers[broker_name]
        except KeyError:
            raise AssertionError(f"No Broker registered with name {broker_name}")

    @property
    def brokers_list(self):
        """A generator that helps users iterator through brokers"""
        if self._brokers is None:
            self._initialize_brokers()

        for broker_name in self._brokers:
            yield self._brokers[broker_name]

    def publish(self, domain_event):
        """Publish a domain event to all registered brokers"""
        if self._brokers is None:
            self._initialize_brokers()

        # Log event into a table before pushing to brokers. This will give a chance to recover from errors.
        #   There is a pseudo-check to ensure `EventLog` is registered in the domain, to ensure that apps
        #   know about this functionality and opt for it explicitly.
        #   # FIXME Check if Event Log is enabled in config
        from protean.infra.event_log import EventLog

        if (
            "protean.infra.event_log.EventLog"
            in self._domain_registry._elements[DomainObjects.AGGREGATE.value]
        ):
            event_dao = self.get_dao(EventLog)
            event_dao.create(
                kind=domain_event.__class__.__name__, payload=domain_event.to_dict()
            )

        if current_uow:
            logger.debug(
                f"Recording {domain_event.__class__.__name__} "
                f"with values {domain_event.to_dict()} in {current_uow}"
            )
            current_uow.register_event(domain_event)
        else:
            logger.debug(
                f"Publishing {domain_event.__class__.__name__} with values {domain_event.to_dict()}"
            )
            for broker_name in self._brokers:
                self._brokers[broker_name].send_message(domain_event)

    def publish_command(self, command):
        """Publish a command to registered command handler"""
        if self._brokers is None:
            self._initialize_brokers()

        if current_uow:
            logger.debug(
                f"Recording {command.__class__.__name__} "
                f"with values {command.to_dict()} in {current_uow}"
            )
            current_uow.register_command_handler(command)
        else:
            logger.debug(
                f"Publishing {command.__class__.__name__} with values {command.to_dict()}"
            )
            for broker_name in self._brokers:
                self._brokers[broker_name].send_message(command)

    def _initialize_email_providers(self):
        """Read config file and initialize email providers"""
        configured_email_providers = self.config["EMAIL_PROVIDERS"]
        email_provider_objects = {}

        if configured_email_providers and isinstance(configured_email_providers, dict):
            if "default" not in configured_email_providers:
                raise ConfigurationError("You must define a 'default' email provider")

            for provider_name, conn_info in configured_email_providers.items():
                provider_full_path = conn_info["PROVIDER"]
                provider_module, provider_class = provider_full_path.rsplit(
                    ".", maxsplit=1
                )

                provider_cls = getattr(
                    importlib.import_module(provider_module), provider_class
                )
                email_provider_objects[provider_name] = provider_cls(
                    provider_name, self, conn_info
                )

        self._email_providers = email_provider_objects

    def has_email_provider(self, provider_name):
        if self._email_providers is None:
            self._initialize_email_providers()

        return provider_name in self._email_providers

    def get_email_provider(self, provider_name):
        """Retrieve the email provider object with a given provider name"""
        if self._email_providers is None:
            self._initialize_email_providers()

        try:
            return self._email_providers[provider_name]
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    @property
    def email_providers_list(self):
        """A generator that helps users iterator through email providers"""
        if self._email_providers is None:
            self._initialize_email_providers()

        for provider_name in self._email_providers:
            yield self._email_providers[provider_name]

    def send_email(self, email):
        """Push email through registered provider"""
        if self._email_providers is None:
            self._initialize_email_providers()

        if current_uow:
            logger.debug(
                f"Recording email {email.__class__.__name__} "
                f"to be sent to {repr(email)} in {current_uow}"
            )
            current_uow.register_email(email)
        else:
            logger.debug(
                f"Pushing {email.__class__.__name__} with content {repr(email)}"
            )
            self._email_providers[email.meta_.provider].send_email(email)
