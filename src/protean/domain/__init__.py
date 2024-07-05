"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""

import inspect
import json
import logging
import sys
from collections import defaultdict
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from werkzeug.datastructures import ImmutableDict

from protean.adapters import Brokers, Caches, EmailProviders, Providers
from protean.adapters.event_store import EventStore
from protean.core.aggregate import element_to_fact_event
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.model import BaseModel
from protean.core.repository import BaseRepository
from protean.domain.registry import _DomainRegistry
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import HasMany, HasOne, Reference, ValueObject
from protean.globals import g
from protean.reflection import declared_fields, has_fields, id_field
from protean.utils import (
    CommandProcessing,
    DomainObjects,
    EventProcessing,
    fqn,
)

from .config import Config2, ConfigAttribute
from .context import DomainContext, _DomainContextGlobals
from .helpers import get_debug_flag, get_env

logger = logging.getLogger(__name__)

# a singleton sentinel value for parameter defaults
_sentinel = object()


class Domain:
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

    from protean.utils import IdentityStrategy, IdentityType

    config_class = Config2
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
    env = ConfigAttribute("env")

    #: The testing flag.  Set this to ``True`` to enable the test mode of
    #: Protean extensions (and in the future probably also Protean itself).
    #: For example this might activate test helpers that have an
    #: additional runtime cost which should not be enabled by default.
    #:
    #: This attribute can also be configured from the config with the
    #: ``testing`` configuration key.  Defaults to ``False``.
    testing = ConfigAttribute("testing")

    #: If a secret key is set, cryptographic components can use this to
    #: sign cookies and other things. Set this to a complex random value
    #: when you want to use the secure cookie for instance.
    #:
    #: This attribute can also be configured from the config with the
    #: :data:`secret_key` configuration key. Defaults to ``None``.
    secret_key = ConfigAttribute("secret_key")

    default_config = ImmutableDict(
        {
            "env": None,
            "debug": None,
            "secret_key": None,
            "identity_strategy": IdentityStrategy.UUID.value,
            "identity_type": IdentityType.STRING.value,
            "databases": {
                "default": {"provider": "memory"},
                "memory": {"provider": "memory"},
            },
            "event_processing": EventProcessing.ASYNC.value,
            "command_processing": CommandProcessing.ASYNC.value,
            "event_store": {
                "provider": "memory",
            },
            "caches": {
                "default": {
                    "provider": "memory",
                    "TTL": 300,
                }
            },
            "brokers": {"default": {"provider": "inline"}},
            "EMAIL_PROVIDERS": {
                "default": {
                    "provider": "protean.adapters.DummyEmailProvider",
                    "DEFAULT_FROM_EMAIL": "admin@team8solutions.com",
                },
            },
            "SNAPSHOT_THRESHOLD": 10,
        },
    )

    def __init__(
        self,
        root_path: str,
        name: str = "",
        load_toml: bool = True,
        identity_function: Optional[Callable] = None,
    ):
        self.root_path = root_path

        # Initialize the domain with the name of the module if not provided
        # Get the stack frame of the caller of the __init__ method
        caller_frame = inspect.stack()[1]
        # Get the module name from the globals of the frame where the object was instantiated
        self.name = name if name else caller_frame.frame.f_globals["__name__"]

        # FIXME Additional domain attributes: (Think if this is needed)
        #   - Type of Domain: Core, Supporting, Third-party(?)
        #   - Type of Implementation: CRUD, CQRS, ES

        # Registry for all domain Objects
        self._domain_registry = _DomainRegistry()

        #: The configuration dictionary as :class:`Config`.  This behaves
        #: exactly like a regular dictionary but supports additional methods
        #: to load a config from files.
        self.config = self.load_config(load_toml)

        # The function to invoke to generate identity
        self._identity_function = identity_function

        self.providers = Providers(self)
        self.event_store = EventStore(self)
        self.brokers = Brokers(self)
        self.caches = Caches(self)
        self.email_providers = EmailProviders(self)

        # Cache for holding Model to Entity/Aggregate associations
        self._models: Dict[str, BaseModel] = {}
        self._constructed_models: Dict[str, BaseModel] = {}

        #: A list of functions that are called when the domain context
        #: is destroyed.  This is the place to store code that cleans up and
        #: disconnects from databases, for example.
        self.teardown_domain_context_functions: List[Callable] = []

        # Placeholder array for resolving classes referenced by domain elements
        # FIXME Should all protean elements be subclassed from a base element?
        self._pending_class_resolutions: dict[str, Any] = defaultdict(list)

    def init(self, traverse=True):  # noqa: C901
        """Parse the domain folder, and attach elements dynamically to the domain.

        Protean parses all files in the domain file's folder, as well as under it,
        to load elements. So, all domain files are to be nested under the file contain
        the domain definition.

        One can use the `traverse` flag to control this functionality, `True` by default.

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
        if traverse is True:
            self._traverse()

        # Resolve all pending references
        self._resolve_references()

        # Assign Aggregate Clusters
        self._assign_aggregate_clusters()

        # Set Aggregate Cluster Options
        self._set_aggregate_cluster_options()

        # Generate Fact Event Classes
        self._generate_fact_event_classes()

        # Run Validations
        self._validate_domain()

        # Initialize adapters after loading domain
        self._initialize()

    def _traverse(self):
        # Standard Library Imports
        import importlib.util
        import os
        import pathlib

        # Directory containing the domain file
        root_dir = pathlib.PurePath(pathlib.Path(self.root_path).resolve()).parent

        # Parent Directory of the directory containing the domain file
        #
        #   We need this to decipher paths from the root. For example,
        #   say the domain file is in a directory called `test13`, and
        #   we are traversing a subdirectory `auth` inside `test13`.
        #   We need to resolve the module for files in the `auth` directory
        #   as `test13.auth`.
        #
        # This makes relative imports possible
        system_folder_path = pathlib.Path(root_dir).parent

        logger.debug(f"Loading domain from {root_dir}...")

        # Identify subdirectories
        subdirectories = [
            name
            for name in os.listdir(root_dir)
            if os.path.isdir(os.path.join(root_dir, name))
            and name not in ["__pycache__"]
        ]

        directories_to_traverse = [str(root_dir)]  # Include root directory

        # Identify subdirectories that have a toml file
        files_to_check = ["domain.toml", ".domain.toml", "pyproject.toml"]
        for subdirectory in subdirectories:
            subdirectory_path = os.path.join(root_dir, subdirectory)
            if not any(
                file
                for file in files_to_check
                if os.path.isfile(os.path.join(subdirectory_path, file))
            ):
                directories_to_traverse.append(subdirectory_path)

        # Traverse directories one by one
        for directory in directories_to_traverse:
            for filename in os.listdir(directory):
                package_path = directory[len(str(system_folder_path)) + 1 :]
                module_name = package_path.replace(os.sep, ".")
                full_file_path = os.path.join(directory, filename)

                if (
                    os.path.isfile(full_file_path)
                    and os.path.splitext(filename)[1] == ".py"
                    and full_file_path != self.root_path
                ):
                    # Construct the module path to import from
                    if filename != "__init__.py":
                        sub_module_name = os.path.splitext(filename)[0]
                        file_module_name = module_name + "." + sub_module_name
                    else:
                        file_module_name = module_name
                    full_file_path = os.path.join(root_dir, filename)

                    spec = importlib.util.spec_from_file_location(
                        file_module_name, os.path.join(directory, filename)
                    )
                    module = importlib.util.module_from_spec(spec)

                    # Do not load module again if it has already been loaded
                    if module.__name__ not in sys.modules:
                        spec.loader.exec_module(module)

                    logger.debug(f"Loaded {filename}")

    def _initialize(self):
        """Initialize domain dependencies and adapters."""
        self.providers._initialize()
        self.caches._initialize()
        self.brokers._initialize()
        self.event_store._initialize()

    def make_config(self):
        """Used to construct the config; invoked by the Domain constructor."""
        defaults = dict(self.default_config)
        defaults["env"] = get_env()
        defaults["debug"] = get_debug_flag()
        return self.config_class(self.root_path, defaults)

    def load_config(self, load_toml=True):
        """Load configuration from dist or a .toml file."""
        if load_toml:
            config = Config2.load_from_path(self.root_path, dict(self.default_config))
        else:
            config = Config2.load_from_dict(dict(self.default_config))

        # Load Constants
        if "custom" in config:
            for constant, value in config["custom"].items():
                setattr(self, constant, value)

        return config

    def domain_context(self, **kwargs):
        """Create an :class:`~protean.context.DomainContext`. Use as a ``with``
        block to push the context, which will make :data:`current_domain`
        point at this domain.

        ::

            with domain.domain_context():
                init_db()
        """
        return DomainContext(self, **kwargs)

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

    def __str__(self) -> str:
        return f"Domain: {self.name}"

    @property
    @lru_cache()
    def registry(self):
        return self._domain_registry

    def factory_for(self, domain_object_type):
        from protean.core.aggregate import aggregate_factory
        from protean.core.application_service import application_service_factory
        from protean.core.command import command_factory
        from protean.core.command_handler import command_handler_factory
        from protean.core.domain_service import domain_service_factory
        from protean.core.email import email_factory
        from protean.core.entity import entity_factory
        from protean.core.event import domain_event_factory
        from protean.core.event_handler import event_handler_factory
        from protean.core.event_sourced_aggregate import event_sourced_aggregate_factory
        from protean.core.event_sourced_repository import (
            event_sourced_repository_factory,
        )
        from protean.core.model import model_factory
        from protean.core.repository import repository_factory
        from protean.core.serializer import serializer_factory
        from protean.core.subscriber import subscriber_factory
        from protean.core.value_object import value_object_factory
        from protean.core.view import view_factory

        factories = {
            DomainObjects.AGGREGATE.value: aggregate_factory,
            DomainObjects.APPLICATION_SERVICE.value: application_service_factory,
            DomainObjects.COMMAND.value: command_factory,
            DomainObjects.COMMAND_HANDLER.value: command_handler_factory,
            DomainObjects.EVENT.value: domain_event_factory,
            DomainObjects.EVENT_HANDLER.value: event_handler_factory,
            DomainObjects.EVENT_SOURCED_AGGREGATE.value: event_sourced_aggregate_factory,
            DomainObjects.EVENT_SOURCED_REPOSITORY.value: event_sourced_repository_factory,
            DomainObjects.DOMAIN_SERVICE.value: domain_service_factory,
            DomainObjects.EMAIL.value: email_factory,
            DomainObjects.ENTITY.value: entity_factory,
            DomainObjects.MODEL.value: model_factory,
            DomainObjects.REPOSITORY.value: repository_factory,
            DomainObjects.SUBSCRIBER.value: subscriber_factory,
            DomainObjects.SERIALIZER.value: serializer_factory,
            DomainObjects.VALUE_OBJECT.value: value_object_factory,
            DomainObjects.VIEW.value: view_factory,
        }

        if domain_object_type.value not in factories:
            raise IncorrectUsageError(
                {"_entity": [f"Unknown Element Type `{domain_object_type.value}`"]}
            )

        return factories[domain_object_type.value]

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

        factory = self.factory_for(element_type)
        new_cls = factory(element_cls, **kwargs)

        if element_type == DomainObjects.MODEL:
            # Remember model association with aggregate/entity class, for easy fetching
            self._models[fqn(new_cls.meta_.entity_cls)] = new_cls

        # Register element with domain
        self._domain_registry.register_element(new_cls)

        # Resolve or record elements to be resolved

        # 1. Associations
        if has_fields(new_cls):
            for _, field_obj in declared_fields(new_cls).items():
                if isinstance(field_obj, (HasOne, HasMany, Reference)) and isinstance(
                    field_obj.to_cls, str
                ):
                    self._pending_class_resolutions[field_obj.to_cls].append(
                        ("Association", (field_obj, new_cls))
                    )

                if isinstance(field_obj, ValueObject) and isinstance(
                    field_obj.value_object_cls, str
                ):
                    self._pending_class_resolutions[field_obj.value_object_cls].append(
                        ("ValueObject", (field_obj, new_cls))
                    )

        # 2. Meta Linkages
        if element_type in [
            DomainObjects.ENTITY,
            DomainObjects.EVENT,
            DomainObjects.EVENT_HANDLER,
            DomainObjects.COMMAND,
            DomainObjects.COMMAND_HANDLER,
            DomainObjects.REPOSITORY,
            DomainObjects.EVENT_SOURCED_REPOSITORY,
        ]:
            if isinstance(new_cls.meta_.part_of, str):
                self._pending_class_resolutions[new_cls.meta_.part_of].append(
                    ("AggregateCls", (new_cls))
                )

        return new_cls

    def _resolve_references(self):
        """Resolve pending class references in association fields.

        Called by the domain context when domain is activated.
        """
        for name in list(self._pending_class_resolutions.keys()):
            for resolution_type, params in self._pending_class_resolutions[name]:
                if resolution_type == "Association":
                    field_obj, owner_cls = params
                    to_cls = self.fetch_element_cls_from_registry(
                        field_obj.to_cls,
                        (
                            DomainObjects.AGGREGATE,
                            DomainObjects.EVENT_SOURCED_AGGREGATE,
                            DomainObjects.ENTITY,
                        ),
                    )
                    field_obj._resolve_to_cls(self, to_cls, owner_cls)
                elif resolution_type == "ValueObject":
                    field_obj, owner_cls = params
                    to_cls = self.fetch_element_cls_from_registry(
                        field_obj.value_object_cls,
                        (DomainObjects.VALUE_OBJECT,),
                    )
                    field_obj._resolve_to_cls(self, to_cls, owner_cls)
                elif resolution_type == "AggregateCls":
                    cls = params
                    to_cls = self.fetch_element_cls_from_registry(
                        cls.meta_.part_of,
                        (
                            DomainObjects.AGGREGATE,
                            DomainObjects.EVENT_SOURCED_AGGREGATE,
                        ),
                    )
                    cls.meta_.part_of = to_cls

                    # Also set the stream name if there is a `stream_name` option in `meta_`
                    # FIXME Could this task be pushed to the element itself, so each element
                    #   can do stuff beyond `stream_name`?
                    if hasattr(cls.meta_, "stream_name") and not cls.meta_.stream_name:
                        cls.meta_.stream_name = to_cls.meta_.stream_name

            # Remove from pending list now that the class has been resolved
            del self._pending_class_resolutions[name]

    # _cls should never be specified by keyword, so start it with an
    # underscore.  The presence of _cls is used to detect if this
    # decorator is being called with parameters or not.
    def _domain_element(
        self,
        element_type,
        _cls=None,
        **kwargs,
    ):
        """Returns the registered class after decoarating it and recording its presence in the domain"""

        def wrap(cls):
            return self._register_element(element_type, cls, **kwargs)

        # See if we're being called as @Entity or @Entity().
        if _cls is None:
            # We're called with parens.
            return wrap

        # We're called as @dataclass without parens.
        return wrap(_cls)

    def register_model(self, model_cls, **kwargs):
        """Register a model class"""
        return self._register_element(DomainObjects.MODEL, model_cls, **kwargs)

    def register(self, element_cls: Any, **kwargs: dict) -> Any:
        """Register an element with the domain.

        Returns the fully-formed domain element, subclassed and associated with
        all traits necessary for its element type.
        """

        # Reject unknown Domain Elements, identified by the absence of `element_type` class var
        if getattr(element_cls, "element_type", None) not in [
            element for element in DomainObjects
        ]:
            raise NotSupportedError(
                f"Element `{element_cls.__name__}` is not a valid element class"
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

    def fetch_element_cls_from_registry(
        self, element: Union[str, Any], element_types: Tuple[DomainObjects, ...]
    ) -> Any:
        """Util Method to fetch an Element's class from its name"""
        if isinstance(element, str):
            try:
                # Try fetching by class name
                return self._get_element_by_name(element_types, element).cls
            except ConfigurationError:
                try:
                    # Try fetching by fully qualified class name
                    return self._get_element_by_fully_qualified_name(
                        element_types, element
                    ).cls
                except ConfigurationError:
                    # Element has not been registered
                    # FIXME print a helpful debug message
                    raise
        else:
            # FIXME Check if entity is subclassed from BaseEntity
            return element

    def _get_element_by_name(self, element_types, element_name):
        """Fetch Domain record with the provided Element name"""
        try:
            elements = self._domain_registry._elements_by_name[element_name]

            # There is one element registered with the name and the correct type
            if len(elements) == 1 and elements[0].class_type in [
                o.value for o in element_types
            ]:
                return elements[0]
            else:
                # There are multiple elements registered with the name
                #   Loop to check if one of them has the correct type
                for element in elements:
                    if element.class_type in [o.value for o in element_types]:
                        return element
                else:
                    raise ConfigurationError(
                        {
                            "element": f"Element {element_name} not registered in domain {self.name}"
                        }
                    )
        except KeyError:
            raise ConfigurationError(
                {
                    "element": f"Element {element_name} not registered in domain {self.name}"
                }
            )

    def _get_element_by_fully_qualified_name(self, element_types, element_fq_name):
        """Fetch Domain record with the Fully Qualified Element name"""
        for element_type in element_types:
            if element_fq_name in self._domain_registry._elements[element_type.value]:
                return self._domain_registry._elements[element_type.value][
                    element_fq_name
                ]
        else:
            raise ConfigurationError(
                {
                    "element": f"Element {element_fq_name} not registered in domain {self.name}"
                }
            )

    def _get_element_by_class(self, element_types, element_cls):
        """Fetch Domain record with Element class details"""
        element_qualname = fqn(element_cls)
        return self._get_element_by_fully_qualified_name(
            element_types, element_qualname
        )

    def _replace_element_by_class(self, new_element_cls):
        aggregate_record = self._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY), new_element_cls
        )

        self._domain_registry._elements[aggregate_record.class_type][
            aggregate_record.qualname
        ].cls = new_element_cls

    def _validate_domain(self):
        """A method to validate the domain for correctness, called just before the domain is activated."""
        # Check `identity_function` is provided if `identity_strategy` is `function`
        if self.config["identity_strategy"] == self.IdentityStrategy.FUNCTION.value:
            if not self._identity_function:
                raise ConfigurationError(
                    {
                        "element": "Identity Strategy is set to `function`, but no Identity Function is provided"
                    }
                )

        # Check if all references are resolved
        if self._pending_class_resolutions:
            raise ConfigurationError(
                {
                    "element": f"Unresolved references in domain {self.name}",
                    "unresolved": self._pending_class_resolutions,
                }
            )

        # Confirm `HasOne` and `HasMany` fields are linked to entities and not aggregates
        for _, aggregate in self.registry.aggregates.items():
            for _, field_obj in declared_fields(aggregate.cls).items():
                if isinstance(field_obj, (HasOne, HasMany)):
                    if isinstance(field_obj.to_cls, str):
                        raise IncorrectUsageError(
                            {
                                "element": (
                                    f"Unresolved target `{field_obj.to_cls}` for field "
                                    f"`{aggregate.__name__}:{field_obj.name}`"
                                )
                            }
                        )
                    if field_obj.to_cls.element_type != DomainObjects.ENTITY:
                        raise IncorrectUsageError(
                            {
                                "element": (
                                    f"Field `{field_obj.field_name}` in `{aggregate.cls.__name__}` "
                                    "is not linked to an Entity class"
                                )
                            }
                        )

        # Check that no two event sourced aggregates have the same event class in their
        #   `_events_cls_map`.
        event_sourced_aggregates = self.registry._elements[
            DomainObjects.EVENT_SOURCED_AGGREGATE.value
        ]
        # Collect all event class names from `_events_cls_map` of all event sourced aggregates
        event_class_names = list()
        for event_sourced_aggregate in event_sourced_aggregates.values():
            event_class_names.extend(event_sourced_aggregate.cls._events_cls_map.keys())
        # Check for duplicates
        duplicate_event_class_names = set(
            [
                event_class_name
                for event_class_name in event_class_names
                if event_class_names.count(event_class_name) > 1
            ]
        )
        if len(duplicate_event_class_names) != 0:
            raise IncorrectUsageError(
                {
                    "_event": [
                        f"Events are associated with multiple event sourced aggregates: "
                        f"{', '.join(duplicate_event_class_names)}"
                    ]
                }
            )

        # Check that entities have the same provider as the aggregate
        for _, entity in self.registry._elements[DomainObjects.ENTITY.value].items():
            if (
                entity.cls.meta_.aggregate_cluster.meta_.provider
                != entity.cls.meta_.provider
            ):
                raise IncorrectUsageError(
                    {
                        "element": (
                            f"Entity `{entity.cls.__name__}` has a different provider "
                            f"than its aggregate `{entity.cls.meta_.aggregate_cluster.__name__}`"
                        )
                    }
                )

    def _assign_aggregate_clusters(self):
        """Assign Aggregate Clusters to all relevant elements"""
        from protean.core.aggregate import BaseAggregate
        from protean.core.event_sourced_aggregate import BaseEventSourcedAggregate

        # Assign Aggregates and EventSourcedAggregates to their own cluster
        for element_type in [
            DomainObjects.AGGREGATE,
            DomainObjects.EVENT_SOURCED_AGGREGATE,
        ]:
            for _, element in self.registry._elements[element_type.value].items():
                element.cls.meta_.aggregate_cluster = element.cls

        # Derive root aggregate for other elements and assign as aggregate_cluster
        for element_type in [
            DomainObjects.ENTITY,
            DomainObjects.EVENT,
            DomainObjects.COMMAND,
        ]:
            for _, element in self.registry._elements[element_type.value].items():
                part_of = element.cls.meta_.part_of
                if part_of:
                    # Traverse up the graph tree to find the root aggregate
                    while not issubclass(
                        part_of, (BaseAggregate, BaseEventSourcedAggregate)
                    ):
                        part_of = part_of.meta_.part_of

                element.cls.meta_.aggregate_cluster = part_of

    def _set_aggregate_cluster_options(self):
        for element_type in [DomainObjects.ENTITY]:
            for _, element in self.registry._elements[element_type.value].items():
                if not hasattr(element.cls.meta_, "provider"):
                    setattr(
                        element.cls.meta_,
                        "provider",
                        element.cls.meta_.aggregate_cluster.meta_.provider,
                    )

    def _generate_fact_event_classes(self):
        """Generate FactEvent classes for all aggregates with `fact_events` enabled"""
        for element_type in [
            DomainObjects.AGGREGATE,
            DomainObjects.EVENT_SOURCED_AGGREGATE,
        ]:
            for _, element in self.registry._elements[element_type.value].items():
                if element.cls.meta_.fact_events:
                    event_cls = element_to_fact_event(element.cls)
                    self.register(event_cls, part_of=element.cls)

    ######################
    # Element Decorators #
    ######################

    def aggregate(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.AGGREGATE,
            _cls=_cls,
            **kwargs,
        )

    def application_service(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.APPLICATION_SERVICE,
            _cls=_cls,
            **kwargs,
        )

    def command(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.COMMAND,
            _cls=_cls,
            **kwargs,
        )

    def command_handler(self, _cls=None, **kwargs):
        return self._domain_element(DomainObjects.COMMAND_HANDLER, _cls=_cls, **kwargs)

    def event(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.EVENT,
            _cls=_cls,
            **kwargs,
        )

    def event_handler(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.EVENT_HANDLER,
            _cls=_cls,
            **kwargs,
        )

    def event_sourced_aggregate(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.EVENT_SOURCED_AGGREGATE,
            _cls=_cls,
            **kwargs,
        )

    def domain_service(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.DOMAIN_SERVICE,
            _cls=_cls,
            **kwargs,
        )

    def entity(self, _cls=None, **kwargs):
        return self._domain_element(DomainObjects.ENTITY, _cls=_cls, **kwargs)

    def email(self, _cls=None, **kwargs):
        return self._domain_element(DomainObjects.EMAIL, _cls=_cls, **kwargs)

    def model(self, _cls=None, **kwargs):
        return self._domain_element(DomainObjects.MODEL, _cls=_cls, **kwargs)

    def repository(self, _cls=None, **kwargs):
        return self._domain_element(DomainObjects.REPOSITORY, _cls=_cls, **kwargs)

    def serializer(self, _cls=None, **kwargs):
        return self._domain_element(DomainObjects.SERIALIZER, _cls=_cls, **kwargs)

    def subscriber(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.SUBSCRIBER,
            _cls=_cls,
            **kwargs,
        )

    def value_object(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.VALUE_OBJECT,
            _cls=_cls,
            **kwargs,
        )

    def view(self, _cls=None, **kwargs):
        return self._domain_element(
            DomainObjects.VIEW,
            _cls=_cls,
            **kwargs,
        )

    ########################
    # Broker Functionality #
    ########################

    def publish(self, events: Union[BaseEvent, List[BaseEvent]]) -> None:
        """Publish Events to all configured brokers.
        Args:
            events (BaseEvent): The Event object containing data to be pushed
        """
        if not isinstance(events, list):
            events = [events]

        for event in events:
            # Persist event in Message Store
            self.event_store.store.append(event)

            self.brokers.publish(event)

            if self.config["event_processing"] == EventProcessing.SYNC.value:
                # Consume events right-away
                handler_classes = self.handlers_for(event)
                for handler_cls in handler_classes:
                    handler_methods = (
                        handler_cls._handlers[fqn(event.__class__)]
                        or handler_cls._handlers["$any"]
                    )

                    for handler_method in handler_methods:
                        handler_method(handler_cls(), event)

    #####################
    # Handling Commands #
    #####################
    def _enrich_command(self, command: BaseCommand) -> BaseCommand:
        # Enrich Command
        identifier = None
        identity_field = id_field(command)
        if identity_field:
            identifier = getattr(command, identity_field.field_name)
        else:
            identifier = str(uuid4())

        stream_name = f"{command.meta_.part_of.meta_.stream_name}:command-{identifier}"

        origin_stream_name = None
        if hasattr(g, "message_in_context"):
            if g.message_in_context.metadata.kind == "EVENT":
                origin_stream_name = g.message_in_context.stream_name

        command_with_metadata = command.__class__(
            command.to_dict(),
            _metadata={
                "id": (str(uuid4())),
                "type": (
                    f"{command.meta_.part_of.__class__.__name__}.{command.__class__.__name__}."
                    f"{command._metadata.version}"
                ),
                "kind": "EVENT",
                "stream_name": stream_name,
                "origin_stream_name": origin_stream_name,
                "timestamp": command._metadata.timestamp,
                "version": command._metadata.version,
                "sequence_id": None,
                "payload_hash": hash(
                    json.dumps(
                        command.payload,
                        sort_keys=True,
                    )
                ),
            },
        )

        return command_with_metadata

    def process(self, command: BaseCommand, asynchronous: bool = True) -> Optional[Any]:
        """Process command and return results based on specified preference.

        By default, Protean does not return values after processing commands. This behavior
        can be overridden either by setting command_processing in config to "sync" or by specifying
        ``asynchronous=False`` when calling the domain's ``handle`` method.

        Args:
            command (BaseCommand): Command to process
            asynchronous (Boolean, optional): Specifies if the command should be processed asynchronously.
                Defaults to True.

        Returns:
            Optional[Any]: Returns either the command handler's return value or nothing, based on preference.
        """
        command_with_metadata = self._enrich_command(command)
        position = self.event_store.store.append(command_with_metadata)

        if (
            not asynchronous
            or self.config["command_processing"] == CommandProcessing.SYNC.value
        ):
            handler_class = self.command_handler_for(command)
            if handler_class:
                handler_method = next(
                    iter(handler_class._handlers[fqn(command.__class__)])
                )
                handler_method(handler_class(), command)

        return position

    def command_handler_for(self, command: BaseCommand) -> Optional[BaseCommandHandler]:
        """Return Command Handler for a specific command.

        Args:
            command (BaseCommand): Command to process

        Returns:
            Optional[BaseCommandHandler]: Command Handler registered to process the command
        """
        return self.event_store.command_handler_for(command)

    ###################
    # Handling Events #
    ###################
    def handlers_for(self, event: BaseEvent) -> List[BaseEventHandler]:
        """Return Event Handlers listening to a specific event

        Args:
            event (BaseEvent): Event to be consumed

        Returns:
            List[BaseEventHandler]: Event Handlers that have registered to consume the event
        """
        return self.event_store.handlers_for(event)

    ############################
    # Repository Functionality #
    ############################

    # FIXME Optimize calls to this method with cache, but also with support for Multitenancy
    def repository_for(self, part_of) -> BaseRepository:
        if isinstance(part_of, str):
            raise IncorrectUsageError(
                {
                    "element": [
                        f"Element {part_of} is not registered in domain {self.name}"
                    ]
                }
            )

        if part_of.element_type == DomainObjects.EVENT_SOURCED_AGGREGATE:
            return self.event_store.repository_for(part_of)
        else:
            return self.providers.repository_for(part_of)

    #######################
    # Cache Functionality #
    #######################

    def cache_for(self, view_cls):
        return self.caches.cache_for(view_cls)

    #######################
    # Email Functionality #
    #######################

    def get_email_provider(self, provider_name):
        return self.email_providers.get_email_provider(provider_name)

    def send_email(self, email):
        return self.email_providers.send_email(email)

    def make_shell_context(self):
        """Return a dictionary of context variables for a shell session."""
        values = {"domain": self}

        # For each domain element type in Domain Objects,
        #   Cycle through all values in self.registry._elements[element_type]
        #   and add each class to the shell context by the key
        for element_type in DomainObjects:
            values.update(
                {
                    v.name: v.cls
                    for _, v in self._domain_registry._elements[
                        element_type.value
                    ].items()
                }
            )

        return values
