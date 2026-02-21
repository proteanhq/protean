"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""

import inspect
import logging
import os
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    dataclass_transform,
    overload,
)

if TYPE_CHECKING:
    from protean.utils.projection_rebuilder import RebuildResult
from uuid import uuid4

from inflection import parameterize, titleize, transliterate, underscore, camelize

from protean.adapters import Brokers, Caches, EmailProviders, Providers
from protean.adapters.event_store import EventStore
from protean.core.aggregate import element_to_fact_event
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.database_model import BaseDatabaseModel
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.repository import BaseRepository
from protean.domain.registry import _DomainRegistry
from protean.exceptions import (
    ConfigurationError,
    DuplicateCommandError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import HasMany, HasOne, Reference, ValueObject
from protean.fields.basic import ValueObjectList
from protean.utils import (
    DomainObjects,
    Processing,
    fqn,
    clone_class,
)
from protean.utils.container import Element
from protean.utils.eventing import Metadata, MessageEnvelope, MessageHeaders, DomainMeta
from protean.utils.globals import g
from protean.utils.idempotency import IdempotencyStore
from protean.utils.outbox import Outbox, OutboxRepository
from protean.utils.reflection import declared_fields, has_fields, id_field

from .config import Config2, ConfigAttribute
from .context import DomainContext, _DomainContextGlobals

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

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
        domain = Domain()

    The Domain will automatically detect the root path of the calling module.
    You can also specify the root path explicitly::

        domain = Domain(root_path="/path/to/domain")

    The root path resolution follows this priority:
    1. Explicit `root_path` parameter if provided
    2. `DOMAIN_ROOT_PATH` environment variable if set
    3. Auto-detection of caller's file location
    4. Current working directory as last resort

    :param root_path: the path to the folder containing the domain file
                      (optional, will auto-detect if not provided)
    :param name: the name of the domain (optional, will use the module name if not provided)
    :param config: optional configuration dictionary
    :param identity_function: optional function to generate identities for domain objects
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
    #: Default: ``'development'``
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

    def _is_interactive_context(self, filename):
        """Check if the given filename indicates an interactive context like shell or notebook.

        Args:
            filename: The code filename to check

        Returns:
            bool: True if filename indicates interactive context, False otherwise
        """
        if filename is None:
            return False
        return filename in {"<stdin>", "<ipython-input>", "<string>", "<console>"}

    def _guess_caller_path(self) -> str:
        """Attempts to determine the path of the caller script or module.

        Returns the path of the file that called the Domain constructor.
        Falls back to current working directory if no file path can be determined.

        This handles various execution contexts:
        - Standard Python scripts
        - Jupyter/IPython notebooks
        - REPL/interactive shell
        - Frozen/PyInstaller applications
        """
        try:
            # Get the frame of the caller of the Domain constructor (2 frames up)
            frame = sys._getframe(2)
            filename = frame.f_code.co_filename

            # Handle special cases
            if self._is_interactive_context(filename):
                # Interactive shell or Jupyter notebook
                return str(Path.cwd())

            # Handle frozen applications (PyInstaller, etc.)
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                # PyInstaller creates a temp folder and stores path in _MEIPASS
                return getattr(sys, "_MEIPASS")

            # Regular Python script
            try:
                return str(Path(filename).resolve().parent)
            except (TypeError, ValueError):
                # Fallback to CWD if unable to determine path
                return str(Path.cwd())
        except Exception:
            # Final fallback for any other unexpected errors
            return str(Path.cwd())

    def __init__(
        self,
        root_path: str = None,
        name: str = "",
        config: Optional[Dict] = None,
        identity_function: Optional[Callable] = None,
    ):
        # Determine root_path based on resolution priority
        if root_path is None:
            # Try to get from environment variable
            env_root_path = os.environ.get("DOMAIN_ROOT_PATH")
            if env_root_path:
                self.root_path = env_root_path
            else:
                # Auto-detect
                self.root_path = self._guess_caller_path()
        else:
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
        self.config = self.load_config(config)

        # The function to invoke to generate identity
        self._identity_function = identity_function

        self.providers = Providers(self)
        self.event_store = EventStore(self)
        self.brokers = Brokers(self)
        self.caches = Caches(self)
        self.email_providers = EmailProviders(self)

        # Cache for holding Model to Entity/Aggregate associations
        self._database_models: Dict[str, BaseDatabaseModel] = {}
        self._constructed_models: Dict[str, BaseDatabaseModel] = {}

        # Cache for holding events and commands by their types
        self._events_and_commands: Dict[str, Union[BaseCommand, BaseEvent]] = {}

        # Upcaster infrastructure (lightweight, not full domain elements)
        from protean.utils.upcasting import UpcasterChain

        self._upcasters: list[type] = []
        self._upcaster_chain: UpcasterChain = UpcasterChain()

        #: A list of functions that are called when the domain context
        #: is destroyed.  This is the place to store code that cleans up and
        #: disconnects from databases, for example.
        self.teardown_domain_context_functions: List[Callable] = []

        # Placeholder array for resolving classes referenced by domain elements
        # FIXME Should all protean elements be subclassed from a base element?
        self._pending_class_resolutions: dict[str, Any] = defaultdict(list)

        # Store outbox DAOs per provider
        self._outbox_repos = {}

        # Lazy-initialized idempotency store
        self._idempotency_store = None

    @property
    def has_outbox(self) -> bool:
        """Whether the outbox pattern is active.

        Derived from ``server.default_subscription_type``: outbox is enabled
        when subscription type is ``"stream"``.  For backward compatibility,
        an explicit ``enable_outbox = true`` also activates the outbox.
        """
        subscription_type = self.config.get("server", {}).get(
            "default_subscription_type", "event_store"
        )
        explicit_outbox = self.config.get("enable_outbox", False)
        return subscription_type == "stream" or explicit_outbox is True

    @property
    def idempotency_store(self):
        """Lazily initialize and return the idempotency store.

        The store is created on first access using the ``idempotency``
        section of the domain config. Returns an ``IdempotencyStore``
        instance (which may be inactive if no Redis URL is configured).
        """
        if self._idempotency_store is None:
            idem_config = self.config.get("idempotency", {})
            self._idempotency_store = IdempotencyStore(
                redis_url=idem_config.get("redis_url"),
                ttl=idem_config.get("ttl", 86400),
                error_ttl=idem_config.get("error_ttl", 60),
            )
        return self._idempotency_store

    @property
    @lru_cache()
    def camel_case_name(self) -> str:
        """Return the CamelCase name of the domain.

        The CamelCase name is the name of the domain with the first letter capitalized.
        Examples:
        - `my_domain` -> `MyDomain`
        - `my_domain_1` -> `MyDomain1`
        - `my_domain_1_0` -> `MyDomain10`
        """
        # Transliterating the name to remove any special characters and camelize
        formatted_string = titleize(transliterate(self.name).replace("-", " "))

        # Eliminate non-alphanumeric characters
        return "".join(filter(str.isalnum, formatted_string))

    @property
    @lru_cache()
    def normalized_name(self) -> str:
        """Return the normalized name of the domain.

        The normalized name is the underscored version of the domain name.
        Examples:
        - `MyDomain` -> `my_domain`
        - `My Domain` -> `my_domain`
        - `My-Domain` -> `my_domain`
        - `My Domain 1` -> `my_domain_1`
        - `My Domain 1.0` -> `my_domain_1_0`
        """
        return underscore(parameterize(transliterate(self.name)))

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

        # Generate and set event/command `__type__` value
        self._set_and_record_event_and_command_type()

        # Build upcaster chains for event schema evolution
        self._build_upcaster_chains()

        # Parse and setup handler methods in Command Handlers
        self._setup_command_handlers()

        # Parse and setup handler methods in Event Handlers
        self._setup_event_handlers()

        # Parse and setup handler methods in Projectors
        self._setup_projectors()

        # Parse and setup handler methods in Process Managers
        self._setup_process_managers()

        # Run Validations
        self._validate_domain()

        # Initialize adapters after loading domain
        self._initialize()

        # Validate outbox / subscription-type consistency
        subscription_type = self.config.get("server", {}).get(
            "default_subscription_type", "event_store"
        )
        if (
            self.config.get("enable_outbox", False)
            and subscription_type == "event_store"
        ):
            raise ConfigurationError(
                "Configuration conflict: 'enable_outbox' is True but "
                "'server.default_subscription_type' is 'event_store'. "
                "When outbox is enabled, subscription type must be 'stream' "
                "so that subscriptions read from the broker where the outbox publishes. "
                "Either set server.default_subscription_type = 'stream' or remove enable_outbox."
            )

        # Validate priority lanes configuration
        lanes_config = self.config.get("server", {}).get("priority_lanes", {})
        if lanes_config:
            enabled = lanes_config.get("enabled", False)
            if not isinstance(enabled, bool):
                raise ConfigurationError(
                    f"server.priority_lanes.enabled must be a bool, "
                    f"got {type(enabled).__name__}: {enabled!r}"
                )

            threshold = lanes_config.get("threshold", 0)
            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                raise ConfigurationError(
                    f"server.priority_lanes.threshold must be an integer, "
                    f"got {type(threshold).__name__}: {threshold!r}"
                )

            suffix = lanes_config.get("backfill_suffix", "backfill")
            if not isinstance(suffix, str) or not suffix.strip():
                raise ConfigurationError(
                    f"server.priority_lanes.backfill_suffix must be a non-empty string, "
                    f"got {type(suffix).__name__}: {suffix!r}"
                )

        # Initialize outbox DAOs for all providers
        if self.has_outbox:
            self._initialize_outbox()

    def _traverse(self):
        # Standard Library Imports
        import importlib.util
        import os
        import pathlib

        # Ensure root_path is a directory path
        root_path = Path(self.root_path)
        if root_path.is_file():
            # If it's a file path (e.g. from __file__), get the parent directory
            root_dir = root_path.parent
        else:
            # It's already a directory
            root_dir = root_path

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
        #   And ignore them from traversal
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
                    and not self._is_domain_file(full_file_path)
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

                    # Register in sys.modules before execution to prevent
                    # duplicate loading if another module imports this one
                    # during execution (e.g., circular or relative imports).
                    if module.__name__ not in sys.modules:
                        sys.modules[module.__name__] = module
                        assert spec is not None and spec.loader is not None
                        spec.loader.exec_module(module)

                    logger.debug(f"Loaded {filename}")

    def _is_domain_file(self, file_path):
        """Check if this is the domain file itself, to avoid self-import.

        This replaces the direct path comparison that was used before.
        """
        if not Path(file_path).is_file():
            return False

        # Get the frame where the Domain was instantiated
        frame = sys._getframe(0)
        while frame:
            if frame.f_code.co_filename == file_path:
                return True
            frame = frame.f_back

        return False

    def _initialize(self):
        """Initialize domain dependencies and adapters."""
        self.providers._initialize()
        self.caches._initialize()
        self.brokers._initialize()
        self.event_store._initialize()

    def load_config(self, config=None):
        """Load configuration from a dict or a .toml file."""
        if config is not None:
            config_obj = Config2.load_from_dict(config)
        else:
            config_obj = Config2.load_from_path(self.root_path)

        # Load Constants
        if "custom" in config_obj:
            for constant, value in config_obj["custom"].items():
                setattr(self, constant, value)

        return config_obj

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
        from protean.core.database_model import database_model_factory
        from protean.core.domain_service import domain_service_factory
        from protean.core.email import email_factory
        from protean.core.entity import entity_factory
        from protean.core.event import domain_event_factory
        from protean.core.event_handler import event_handler_factory
        from protean.core.event_sourced_repository import (
            event_sourced_repository_factory,
        )
        from protean.core.projection import projection_factory
        from protean.core.projector import projector_factory
        from protean.core.repository import repository_factory
        from protean.core.subscriber import subscriber_factory
        from protean.core.value_object import value_object_factory

        from protean.core.process_manager import process_manager_factory

        factories = {
            DomainObjects.AGGREGATE.value: aggregate_factory,
            DomainObjects.APPLICATION_SERVICE.value: application_service_factory,
            DomainObjects.COMMAND.value: command_factory,
            DomainObjects.COMMAND_HANDLER.value: command_handler_factory,
            DomainObjects.EVENT.value: domain_event_factory,
            DomainObjects.EVENT_HANDLER.value: event_handler_factory,
            DomainObjects.EVENT_SOURCED_REPOSITORY.value: event_sourced_repository_factory,
            DomainObjects.DOMAIN_SERVICE.value: domain_service_factory,
            DomainObjects.EMAIL.value: email_factory,
            DomainObjects.ENTITY.value: entity_factory,
            DomainObjects.DATABASE_MODEL.value: database_model_factory,
            DomainObjects.PROCESS_MANAGER.value: process_manager_factory,
            DomainObjects.REPOSITORY.value: repository_factory,
            DomainObjects.SUBSCRIBER.value: subscriber_factory,
            DomainObjects.VALUE_OBJECT.value: value_object_factory,
            DomainObjects.PROJECTION.value: projection_factory,
            DomainObjects.PROJECTOR.value: projector_factory,
        }

        if domain_object_type.value not in factories:
            raise IncorrectUsageError(
                f"Unknown Element Type `{domain_object_type.value}`"
            )

        return factories[domain_object_type.value]

    def _register_element(
        self,
        element_type: DomainObjects,
        element_cls: type[_T],
        internal: bool = False,
        **opts: Any,
    ) -> type[_T]:  # noqa: C901
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
        new_cls = factory(element_cls, self, **opts)

        if element_type == DomainObjects.DATABASE_MODEL:
            # Remember model association with aggregate/entity class, for easy fetching
            self._database_models[fqn(new_cls.meta_.part_of)] = new_cls

        # Register element with domain
        self._domain_registry.register_element(new_cls, internal)

        # Resolve or record elements to be resolved

        # 1. Associations
        if has_fields(new_cls):
            for _, field_obj in declared_fields(new_cls).items():
                # Record Association references to resolve later
                if isinstance(field_obj, (HasOne, HasMany, Reference)) and isinstance(
                    field_obj.to_cls, str
                ):
                    self._pending_class_resolutions[field_obj.to_cls].append(
                        ("Association", (field_obj, new_cls))
                    )

                # Record Value Object references to resolve later
                if isinstance(field_obj, ValueObject) and isinstance(
                    field_obj.value_object_cls, str
                ):
                    self._pending_class_resolutions[field_obj.value_object_cls].append(
                        ("ValueObject", (field_obj, new_cls))
                    )

                # Record Value Object references in List fields to resolve later
                if (
                    isinstance(field_obj, ValueObjectList)
                    and isinstance(field_obj.content_type, ValueObject)
                    and isinstance(field_obj.content_type.value_object_cls, str)
                ):
                    self._pending_class_resolutions[
                        field_obj.content_type.value_object_cls
                    ].append(("ValueObject", (field_obj.content_type, new_cls)))

            # Also scan FieldSpec metadata for ValueObject descriptors
            # (e.g. List(content_type=ValueObject("InnerVO")))
            field_meta = getattr(new_cls, "__protean_field_meta__", {})
            for _, spec in field_meta.items():
                ct = getattr(spec, "content_type", None)
                if isinstance(ct, ValueObject) and isinstance(ct.value_object_cls, str):
                    self._pending_class_resolutions[ct.value_object_cls].append(
                        ("ValueObject", (ct, new_cls))
                    )

        # 2. Meta Linkages
        if element_type in [
            DomainObjects.APPLICATION_SERVICE,
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

        if element_type == DomainObjects.PROJECTOR:
            if isinstance(new_cls.meta_.projector_for, str):
                self._pending_class_resolutions[new_cls.meta_.projector_for].append(
                    ("ProjectionCls", (new_cls))
                )

        return new_cls

    def _resolve_references(self):
        """Resolve pending class references in association fields.

        Called by the domain context when domain is activated.
        """
        for name in list(self._pending_class_resolutions.keys()):
            for resolution_type, params in self._pending_class_resolutions[name]:
                match resolution_type:
                    case "Association":
                        field_obj, owner_cls = params
                        to_cls = self.fetch_element_cls_from_registry(
                            field_obj.to_cls,
                            (
                                DomainObjects.AGGREGATE,
                                DomainObjects.ENTITY,
                            ),
                        )
                        field_obj._resolve_to_cls(self, to_cls, owner_cls)
                    case "ValueObject":
                        field_obj, owner_cls = params
                        to_cls = self.fetch_element_cls_from_registry(
                            field_obj.value_object_cls,
                            (DomainObjects.VALUE_OBJECT,),
                        )
                        field_obj._resolve_to_cls(self, to_cls, owner_cls)
                    case "AggregateCls":
                        cls = params
                        to_cls = self.fetch_element_cls_from_registry(
                            cls.meta_.part_of,
                            (DomainObjects.AGGREGATE,),
                        )
                        cls.meta_.part_of = to_cls
                    case "ProjectionCls":
                        cls = params
                        to_cls = self.fetch_element_cls_from_registry(
                            cls.meta_.projector_for,
                            (DomainObjects.PROJECTION,),
                        )
                        cls.meta_.projector_for = to_cls
                    case _:
                        raise NotSupportedError(
                            f"Resolution Type {resolution_type} not supported"
                        )

            # Remove from pending list now that the class has been resolved
            del self._pending_class_resolutions[name]

    # _cls should never be specified by keyword, so start it with an
    # underscore.  The presence of _cls is used to detect if this
    # decorator is being called with parameters or not.
    def _domain_element(
        self,
        element_type: DomainObjects,
        _cls: type | None = None,
        internal: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Returns the registered class after decorating it and recording its presence in the domain"""

        def wrap(cls: type) -> type:
            return self._register_element(element_type, cls, internal, **kwargs)

        # See if we're being called as @Entity or @Entity().
        if _cls is None:
            # We're called with parens.
            return wrap

        # We're called as @dataclass without parens.
        return wrap(_cls)

    def register_database_model(
        self, database_model_cls, internal: bool = False, **kwargs
    ):
        """Register a model class"""
        return self._register_element(
            DomainObjects.DATABASE_MODEL, database_model_cls, internal, **kwargs
        )

    def register(self, element_cls: Any, internal: bool = False, **kwargs: dict) -> Any:
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

        return self._register_element(
            element_cls.element_type, element_cls, internal, **kwargs
        )

    def fetch_element_cls_from_registry(
        self, element: str, element_types: Tuple[DomainObjects, ...]
    ) -> Element:
        """Util Method to fetch an Element's class from its name"""
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
                            f"Unresolved target `{field_obj.to_cls}` for field "
                            f"`{aggregate.__name__}:{field_obj.name}`"
                        )
                    if field_obj.to_cls.element_type != DomainObjects.ENTITY:
                        raise IncorrectUsageError(
                            f"Field `{field_obj.field_name}` in `{aggregate.cls.__name__}` "
                            "is not linked to an Entity class"
                        )

        # Check that no two event sourced aggregates have the same event class in their
        #   `_events_cls_map`.
        event_sourced_aggregates = {
            name: record
            for (name, record) in self.registry._elements[
                DomainObjects.AGGREGATE.value
            ].items()
            if record.cls.meta_.is_event_sourced is True
        }
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
                f"Events are associated with multiple event sourced aggregates: "
                f"{', '.join(duplicate_event_class_names)}"
            )

        # Check that entities have the same provider as the aggregate
        for _, entity in self.registry._elements[DomainObjects.ENTITY.value].items():
            if (
                entity.cls.meta_.aggregate_cluster.meta_.provider
                != entity.cls.meta_.provider
            ):
                raise IncorrectUsageError(
                    f"Entity `{entity.cls.__name__}` has a different provider "
                    f"than its aggregate `{entity.cls.meta_.aggregate_cluster.__name__}`"
                )

        # Check that projections associated with projectors are registered
        for _, projector in self.registry._elements[
            DomainObjects.PROJECTOR.value
        ].items():
            if projector.cls.meta_.projector_for:
                if (
                    fqn(projector.cls.meta_.projector_for)
                    not in self.registry._elements[DomainObjects.PROJECTION.value]
                ):
                    raise IncorrectUsageError(
                        f"`{projector.cls.meta_.projector_for.__name__}` is not a Projection, or is not registered in domain {self.name}"
                    )

    def _assign_aggregate_clusters(self):
        """Assign Aggregate Clusters to all relevant elements"""
        from protean.core.aggregate import BaseAggregate
        from protean.core.process_manager import BaseProcessManager

        # Assign Aggregates, EventSourcedAggregates, and Process Managers to their own cluster
        for element_type in [
            DomainObjects.AGGREGATE,
            DomainObjects.PROCESS_MANAGER,
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
                    # (or process manager, for transition events)
                    while not issubclass(part_of, BaseAggregate) and not issubclass(
                        part_of, BaseProcessManager
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

    def _set_and_record_event_and_command_type(self):
        for element_type in [DomainObjects.EVENT, DomainObjects.COMMAND]:
            for _, element in self.registry._elements[element_type.value].items():
                # Type is <Domain Name>.<Event or Command Name>.<Version>
                # E.g. `Authentication.UserRegistered.v1`, `Ecommerce.OrderPlaced.v1`
                type_string = (
                    f"{self.camel_case_name}."
                    # f"{element.cls.meta_.aggregate_cluster.__class__.__name__}."
                    f"{element.cls.__name__}."
                    f"{element.cls.__version__}"
                )

                setattr(element.cls, "__type__", type_string)

                self._events_and_commands[type_string] = element.cls

    def _build_upcaster_chains(self) -> None:
        """Build upcaster chains from registered upcasters.

        Called during ``init()`` after ``_set_and_record_event_and_command_type``
        so that event type strings are available for chain validation.
        """
        for upcaster_cls in self._upcasters:
            event_type = upcaster_cls.meta_.event_type

            # Compute event_base_type: "DomainName.EventName"
            event_base_type = f"{self.camel_case_name}.{event_type.__name__}"

            self._upcaster_chain.register_upcaster(
                event_base_type=event_base_type,
                from_version=upcaster_cls.meta_.from_version,
                to_version=upcaster_cls.meta_.to_version,
                upcaster_cls=upcaster_cls,
            )

        self._upcaster_chain.build_chains(self._events_and_commands)

    def register_external_event(self, event_cls: Type[BaseEvent], type_string: str):
        """Register an external event with the domain.

        When we are consuming an event generated by another Protean domain, we only want
        to map the event type to a class. We don't want to add the event to this domain's
        registry, since we won't do anything else with this event other than consuming it.
        This method simply maps the external event type manually to the event class,
        bypassing the type string construction process.
        """
        # Ensure class is an event
        if (
            not issubclass(event_cls, BaseEvent)
            or event_cls.element_type != DomainObjects.EVENT
        ):
            raise IncorrectUsageError(f"Class `{event_cls.__name__}` is not an Event")

        self._events_and_commands[type_string] = event_cls

        # Set __type__ on the event class so ProcessManagers and other
        # infrastructure can resolve the type string from the class itself.
        setattr(event_cls, "__type__", type_string)

    def _setup_command_handlers(self):
        for element_type in [DomainObjects.COMMAND_HANDLER]:
            for _, element in self.registry._elements[element_type.value].items():
                # Iterate through methods marked as `@handle` and construct a handler map
                if not element.cls._handlers:  # Protect against re-registration
                    methods = inspect.getmembers(
                        element.cls, predicate=inspect.isroutine
                    )
                    for method_name, method in methods:
                        if not (
                            method_name.startswith("__") and method_name.endswith("__")
                        ) and hasattr(method, "_target_cls"):
                            # Throw error if target_cls is not a Command
                            if not inspect.isclass(
                                method._target_cls
                            ) or not issubclass(method._target_cls, BaseCommand):
                                raise IncorrectUsageError(
                                    f"Method `{method_name}` in Command Handler `{element.cls.__name__}` "
                                    "is not associated with a command"
                                )

                            # Throw error if target_cls is not associated with an aggregate
                            if not method._target_cls.meta_.part_of:
                                raise IncorrectUsageError(
                                    f"Command `{method._target_cls.__name__}` in Command Handler `{element.cls.__name__}` "
                                    "is not associated with an aggregate"
                                )

                            if (
                                method._target_cls.meta_.part_of
                                != element.cls.meta_.part_of
                            ):
                                raise IncorrectUsageError(
                                    f"Command `{method._target_cls.__name__}` in Command Handler `{element.cls.__name__}` "
                                    "is not associated with the same aggregate as the Command Handler"
                                )

                            command_type = (
                                method._target_cls.__type__
                                if issubclass(
                                    method._target_cls,
                                    BaseCommand,
                                )
                                else method._target_cls
                            )

                            # Do not allow multiple handlers per command
                            if (
                                command_type in element.cls._handlers
                                and len(element.cls._handlers[command_type]) != 0
                            ):
                                raise NotSupportedError(
                                    f"Command {method._target_cls.__name__} cannot be handled by multiple handlers"
                                )

                            # `_handlers` maps the command to its handler method
                            element.cls._handlers[command_type].add(method)

    def _setup_event_handlers(self):
        for element_type in [DomainObjects.EVENT_HANDLER]:
            for _, element in self.registry._elements[element_type.value].items():
                # Iterate through methods marked as `@handle` and construct a handler map
                #
                # Also, if `_target_cls` is an event, associate it with the event handler's
                #   aggregate or stream
                methods = inspect.getmembers(element.cls, predicate=inspect.isroutine)
                for method_name, method in methods:
                    if not (
                        method_name.startswith("__") and method_name.endswith("__")
                    ) and hasattr(method, "_target_cls"):
                        # `_handlers` is a dictionary mapping the event to the handler method.
                        if method._target_cls == "$any":
                            # This replaces any existing `$any` handler, by design. An Event Handler
                            # can have only one `$any` handler method.
                            element.cls._handlers["$any"] = {method}
                        else:
                            # Target could be an event or an event type string
                            event_type = (
                                method._target_cls.__type__
                                if issubclass(method._target_cls, BaseEvent)
                                else method._target_cls
                            )
                            element.cls._handlers[event_type].add(method)

    def _setup_projectors(self):
        for element_type in [DomainObjects.PROJECTOR]:
            for _, element in self.registry._elements[element_type.value].items():
                # Iterate through methods marked as `@handle` and construct a handler map
                if not element.cls._handlers:  # Protect against re-registration
                    methods = inspect.getmembers(
                        element.cls, predicate=inspect.isroutine
                    )
                    for method_name, method in methods:
                        if not (
                            method_name.startswith("__") and method_name.endswith("__")
                        ) and hasattr(method, "_target_cls"):
                            # Throw error if target_cls is not an Event
                            if not inspect.isclass(
                                method._target_cls
                            ) or not issubclass(method._target_cls, BaseEvent):
                                raise IncorrectUsageError(
                                    f"Projector method `{method_name}` in `{element.cls.__name__}` "
                                    "is not associated with an event"
                                )

                            event_type = (
                                method._target_cls.__type__
                                if issubclass(method._target_cls, BaseEvent)
                                else method._target_cls
                            )

                            # `_handlers` maps the command to its handler method
                            element.cls._handlers[event_type].add(method)

    def _setup_process_managers(self):
        from protean.core.process_manager import _generate_pm_transition_event

        for _, element in self.registry._elements[
            DomainObjects.PROCESS_MANAGER.value
        ].items():
            pm_cls = element.cls

            # Iterate through methods marked as `@handle` and construct a handler map
            if not pm_cls._handlers:  # Protect against re-registration
                has_start = False

                methods = inspect.getmembers(pm_cls, predicate=inspect.isroutine)
                for method_name, method in methods:
                    if not (
                        method_name.startswith("__") and method_name.endswith("__")
                    ) and hasattr(method, "_target_cls"):
                        # Validate target is an Event
                        if not inspect.isclass(method._target_cls) or not issubclass(
                            method._target_cls, BaseEvent
                        ):
                            raise IncorrectUsageError(
                                f"Process Manager method `{method_name}` in `{pm_cls.__name__}` "
                                "is not associated with an event"
                            )

                        # Validate correlate is specified
                        if not getattr(method, "_correlate", None):
                            raise IncorrectUsageError(
                                f"Handler `{method_name}` in Process Manager "
                                f"`{pm_cls.__name__}` must specify a `correlate` parameter"
                            )

                        if getattr(method, "_start", False):
                            has_start = True

                        event_type = (
                            method._target_cls.__type__
                            if issubclass(method._target_cls, BaseEvent)
                            else method._target_cls
                        )

                        pm_cls._handlers[event_type].add(method)

                if not has_start:
                    raise IncorrectUsageError(
                        f"Process Manager `{pm_cls.__name__}` must have at least "
                        f"one handler with `start=True`"
                    )

            # Generate transition event class
            transition_cls = _generate_pm_transition_event(pm_cls)

            # Register transition event with domain
            self._register_element(
                DomainObjects.EVENT,
                transition_cls,
                internal=True,
                part_of=pm_cls,
            )

            # Set __type__ on the transition event
            type_string = (
                f"{self.camel_case_name}."
                f"{transition_cls.__name__}."
                f"{getattr(transition_cls, '__version__', 'v1')}"
            )
            setattr(transition_cls, "__type__", type_string)
            self._events_and_commands[type_string] = transition_cls

            # Store transition event class on PM
            pm_cls._transition_event_cls = transition_cls

            # If stream_categories is empty, infer from handled events' aggregates
            if not pm_cls.meta_.stream_categories:
                inferred_categories = set()
                for method_name, method in methods:
                    if hasattr(method, "_target_cls") and inspect.isclass(
                        method._target_cls
                    ):
                        target = method._target_cls
                        if hasattr(target, "meta_") and hasattr(
                            target.meta_, "part_of"
                        ):
                            part_of = target.meta_.part_of
                            if part_of and hasattr(part_of, "meta_"):
                                inferred_categories.add(part_of.meta_.stream_category)

                pm_cls.meta_.stream_categories = list(inferred_categories)

    def _generate_fact_event_classes(self):
        """Generate FactEvent classes for all aggregates with `fact_events` enabled"""
        for _, element in self.registry._elements[
            DomainObjects.AGGREGATE.value
        ].items():
            if element.cls.meta_.fact_events:
                event_cls = element_to_fact_event(element.cls)
                self.register(event_cls, part_of=element.cls)

    ######################
    # Element Decorators #
    ######################

    @overload
    def aggregate(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def aggregate(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def aggregate(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.AGGREGATE,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def application_service(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def application_service(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def application_service(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.APPLICATION_SERVICE,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def command(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def command(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def command(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.COMMAND,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def command_handler(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def command_handler(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def command_handler(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.COMMAND_HANDLER, _cls=_cls, **kwargs)

    @overload
    def event(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def event(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def event(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.EVENT,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def event_handler(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def event_handler(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def event_handler(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.EVENT_HANDLER,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def domain_service(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def domain_service(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def domain_service(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.DOMAIN_SERVICE,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def entity(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def entity(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def entity(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.ENTITY, _cls=_cls, **kwargs)

    @overload
    def email(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def email(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def email(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.EMAIL, _cls=_cls, **kwargs)

    @overload
    def database_model(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def database_model(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def database_model(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.DATABASE_MODEL, _cls=_cls, **kwargs)

    @overload
    def repository(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def repository(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def repository(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.REPOSITORY, _cls=_cls, **kwargs)

    @overload
    def subscriber(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def subscriber(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def subscriber(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.SUBSCRIBER,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def value_object(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def value_object(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def value_object(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.VALUE_OBJECT,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def projection(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def projection(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def projection(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.PROJECTION,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def projector(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def projector(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def projector(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.PROJECTOR,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def process_manager(self, _cls: type[_T]) -> type[_T]: ...
    @overload
    def process_manager(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform()
    def process_manager(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.PROCESS_MANAGER,
            _cls=_cls,
            **kwargs,
        )

    ##############
    # Upcasters  #
    ##############
    def upcaster(
        self,
        _cls: type[_T] | None = None,
        **kwargs: Any,
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        """Register an event upcaster with the domain.

        Upcasters transform raw event payloads from an old schema version to
        a newer one.  They are applied lazily during deserialization so that
        ``@apply`` handlers and event handlers always see the current schema.

        Args:
            event_type: The event class this upcaster targets (current version).
            from_version: Source version string (e.g. ``"v1"``).
            to_version: Target version string (e.g. ``"v2"``).

        Example::

            @domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
            class UpcastOrderPlacedV1ToV2(BaseUpcaster):
                def upcast(self, data: dict) -> dict:
                    data["currency"] = "USD"
                    return data
        """
        from protean.core.upcaster import upcaster_factory

        def wrap(cls: type) -> type:
            new_cls = upcaster_factory(cls, self, **kwargs)
            self._upcasters.append(new_cls)
            return new_cls

        if _cls is None:
            return wrap
        return wrap(_cls)

    #####################
    # Handling Commands #
    #####################
    def _enrich_command(
        self,
        command: BaseCommand,
        asynchronous: bool,
        idempotency_key: Optional[str] = None,
        priority: int = 0,
    ) -> BaseCommand:
        # Enrich Command
        identifier = None
        identity_field = id_field(command)
        if identity_field:
            identifier = getattr(command, identity_field.field_name)
        else:
            identifier = str(uuid4())

        stream = f"{command.meta_.part_of.meta_.stream_category}:command-{identifier}"

        origin_stream = None
        if hasattr(g, "message_in_context"):
            if g.message_in_context.metadata.domain.kind == "EVENT":
                origin_stream = g.message_in_context.metadata.headers.stream

        headers = MessageHeaders(
            id=identifier,  # FIXME Double check command ID format and construction
            type=command.__class__.__type__,
            stream=stream,
            time=command._metadata.headers.time
            if (command._metadata.headers and command._metadata.headers.time)
            else None,
            idempotency_key=idempotency_key,
        )

        # Compute envelope with checksum for integrity validation
        envelope = MessageEnvelope.build(command.payload)

        # Build domain metadata
        domain_meta = DomainMeta(
            fqn=command._metadata.domain.fqn
            if command._metadata.domain
            else command._metadata.fqn
            if hasattr(command._metadata, "fqn")
            else None,
            kind="COMMAND",
            origin_stream=origin_stream,
            version=command._metadata.domain.version
            if command._metadata.domain
            else command._metadata.version
            if hasattr(command._metadata, "version")
            else None,
            sequence_id=None,
            asynchronous=asynchronous,
            priority=priority,
        )

        metadata = Metadata(
            headers=headers,
            envelope=envelope,
            domain=domain_meta,
        )

        command_with_metadata = command.__class__(
            command.to_dict(),
            _metadata=metadata,
        )

        return command_with_metadata

    def process(
        self,
        command: Any,
        asynchronous: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        raise_on_duplicate: bool = False,
        priority: Optional[int] = None,
    ) -> Optional[Any]:
        """Process command and return results based on specified preference.

        By default, Protean does not return values after processing commands. This behavior
        can be overridden either by setting command_processing in config to "sync" or by specifying
        ``asynchronous=False`` when calling the domain's ``handle`` method.

        Args:
            command: Command to process (instance of a ``@domain.command``-decorated class)
            asynchronous (Boolean, optional): Specifies if the command should be processed asynchronously.
                Defaults to True.
            idempotency_key (str, optional): Caller-provided key for command deduplication.
                When provided, enables submission-level dedup via the idempotency store.
            raise_on_duplicate (bool): If ``True``, raises :class:`DuplicateCommandError`
                when a duplicate idempotency key is detected. If ``False`` (default),
                silently returns the cached result.
            priority (int, optional): Processing priority for events produced by this command.
                When priority lanes are enabled, events with priority below the configured
                threshold are routed to a backfill stream and processed only when the
                primary stream is empty. Use ``Priority`` enum values from
                ``protean.utils.processing``. If not specified, uses the value from
                the current ``processing_priority()`` context, or ``Priority.NORMAL`` (0).

        Returns:
            Optional[Any]: Returns either the command handler's return value or nothing, based on preference.
        """
        from protean.utils.processing import current_priority, processing_priority

        # If asynchronous is not specified, use the command_processing setting from config
        if asynchronous is None:
            asynchronous = self.config["command_processing"] == Processing.ASYNC.value

        if (
            fqn(command.__class__)
            not in self.registry._elements[DomainObjects.COMMAND.value]
        ):
            raise IncorrectUsageError(
                f"Element {command.__class__.__name__} is not registered in domain {self.name}"
            )

        # --- Idempotency: check for existing result ---
        store = self.idempotency_store
        if idempotency_key and store.is_active:
            existing = store.check(idempotency_key)
            if existing and existing.get("status") == "success":
                cached_result = existing.get("result")
                if raise_on_duplicate:
                    raise DuplicateCommandError(
                        f"Command with idempotency key '{idempotency_key}' "
                        f"has already been processed",
                        original_result=cached_result,
                    )
                return cached_result

        # Resolve priority: explicit param > context var > default (0)
        resolved_priority = priority if priority is not None else current_priority()

        command_with_metadata = self._enrich_command(
            command,
            asynchronous,
            idempotency_key=idempotency_key,
            priority=resolved_priority,
        )
        position = self.event_store.store.append(command_with_metadata)

        if (
            not asynchronous
            or self.config["command_processing"] == Processing.SYNC.value
        ):
            handler_class = self.command_handler_for(command)
            if handler_class:
                try:
                    # Set the processing priority context so that UoW.commit()
                    # can read it when creating outbox records
                    with processing_priority(resolved_priority):
                        result = handler_class._handle(command_with_metadata)
                except Exception:
                    # Record failure with short TTL to allow retry
                    if idempotency_key and store.is_active:
                        store.record_error(idempotency_key, "handler_failed")
                    raise

                # Record success
                if idempotency_key and store.is_active:
                    store.record_success(idempotency_key, result)
                return result

        # Async path: cache the position as the result
        if idempotency_key and store.is_active:
            store.record_success(idempotency_key, position)

        return position

    def command_handler_for(self, command: Any) -> Optional[BaseCommandHandler]:
        """Return Command Handler for a specific command.

        Args:
            command: Command to process (instance of a ``@domain.command``-decorated class)

        Returns:
            Optional[BaseCommandHandler]: Command Handler registered to process the command
        """
        return self.event_store.command_handler_for(command)

    ###################
    # Handling Events #
    ###################
    def handlers_for(self, event: Any) -> set:
        """Return Event Handlers listening to a specific event

        Args:
            event: Event to be consumed (instance of a ``@domain.event``-decorated class)

        Returns:
            List[BaseEventHandler]: Event Handlers that have registered to consume the event
        """
        return self.event_store.handlers_for(event)

    ############################
    # Projector Functionality  #
    ############################
    def projectors_for(self, projection_cls: BaseProjection) -> set:
        """Return Projectors listening to a specific projection

        Args:
            projection_cls (BaseProjection): Projection to be consumed

        Returns:
            List[BaseProjector]: Projectors that have registered to consume the projection
        """
        return self.event_store.projectors_for(projection_cls)

    ############################
    # Repository Functionality #
    ############################

    # FIXME Optimize calls to this method with cache, but also with support for Multitenancy
    def repository_for(self, element_cls) -> BaseRepository:
        if isinstance(element_cls, str):
            raise IncorrectUsageError(
                f"Element {element_cls} is not registered in domain {self.name}"
            )

        if (
            element_cls.element_type == DomainObjects.AGGREGATE
            and element_cls.meta_.is_event_sourced
        ):
            # Return an Event Sourced repository
            return self.event_store.repository_for(element_cls)
        else:
            # This is a regular aggregate or a projection
            return self.providers.repository_for(element_cls)

    #######################
    # Cache Functionality #
    #######################

    def cache_for(self, projection_cls):
        return self.caches.cache_for(projection_cls)

    ##########################
    # Snapshot Functionality #
    ##########################

    def create_snapshot(self, aggregate_cls: type, identifier: str) -> bool:
        """Create a snapshot for a specific event-sourced aggregate instance.

        Must be called after ``domain.init()`` and within ``domain.domain_context()``.

        Args:
            aggregate_cls: The event-sourced aggregate class
            identifier: Unique aggregate identifier

        Returns:
            True if a snapshot was created.

        Raises:
            IncorrectUsageError: If the aggregate is not event-sourced or not registered.
            ObjectNotFoundError: If the aggregate instance does not exist.
        """
        if (
            fqn(aggregate_cls)
            not in self.registry._elements[DomainObjects.AGGREGATE.value]
        ):
            raise IncorrectUsageError(
                f"`{aggregate_cls.__name__}` is not registered in domain {self.name}"
            )

        return self.event_store.store.create_snapshot(aggregate_cls, identifier)

    def create_snapshots(self, aggregate_cls: type) -> int:
        """Create snapshots for all instances of an event-sourced aggregate.

        Must be called after ``domain.init()`` and within ``domain.domain_context()``.

        Args:
            aggregate_cls: The event-sourced aggregate class

        Returns:
            Number of snapshots created.

        Raises:
            IncorrectUsageError: If the aggregate is not event-sourced or not registered.
        """
        if (
            fqn(aggregate_cls)
            not in self.registry._elements[DomainObjects.AGGREGATE.value]
        ):
            raise IncorrectUsageError(
                f"`{aggregate_cls.__name__}` is not registered in domain {self.name}"
            )

        return self.event_store.store.create_snapshots(aggregate_cls)

    def create_all_snapshots(self) -> dict[str, int]:
        """Create snapshots for all event-sourced aggregates in the domain.

        Must be called after ``domain.init()`` and within ``domain.domain_context()``.

        Returns:
            Dictionary mapping aggregate class names to the number of
            snapshots created.
        """
        results: dict[str, int] = {}
        for _, record in self.registry._elements[DomainObjects.AGGREGATE.value].items():
            if record.cls.meta_.is_event_sourced and not record.internal:
                count = self.event_store.store.create_snapshots(record.cls)
                results[record.cls.__name__] = count

        return results

    ####################################
    # Projection Rebuild Functionality #
    ####################################

    def rebuild_projection(
        self, projection_cls: type, batch_size: int = 500
    ) -> "RebuildResult":
        """Rebuild a projection by replaying events through its projectors.

        Truncates existing projection data, then replays all events from the
        event store through each projector that targets this projection.
        Upcasters are applied automatically during replay.

        Must be called after ``domain.init()`` and within
        ``domain.domain_context()``.

        Args:
            projection_cls: The projection class to rebuild.
            batch_size: Number of events to read per batch from the event store.

        Returns:
            RebuildResult with counts and any errors.
        """
        from protean.utils.projection_rebuilder import rebuild_projection

        return rebuild_projection(self, projection_cls, batch_size)

    def rebuild_all_projections(
        self, batch_size: int = 500
    ) -> dict[str, "RebuildResult"]:
        """Rebuild all projections registered in the domain.

        Must be called after ``domain.init()`` and within
        ``domain.domain_context()``.

        Args:
            batch_size: Number of events to read per batch from the event store.

        Returns:
            Dictionary mapping projection class names to their RebuildResult.
        """
        from protean.utils.projection_rebuilder import rebuild_all_projections

        return rebuild_all_projections(self, batch_size)

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

    def _initialize_outbox(self):
        """Initialize outbox repositories for all configured providers.

        This method constructs and stores outbox repositories for each provider,
        verifying that the outbox table exists in the database.
        """

        # Create outbox repositories for each provider
        # Check if providers are available and initialized
        if (
            hasattr(self.providers, "_providers")
            and self.providers._providers is not None
        ):
            for provider_name in self.providers._providers.keys():
                try:
                    # Synthesize new outbox class specific to this provider
                    new_name = f"{camelize(provider_name)}Outbox"
                    new_cls = clone_class(Outbox, new_name)

                    self.register(
                        new_cls,
                        internal=True,
                        schema_name="outbox",
                        provider=provider_name,
                    )

                    # Synthesize new repository class specific to this provider
                    new_repo_name = f"{camelize(provider_name)}OutboxRepository"
                    new_repo_cls = clone_class(OutboxRepository, new_repo_name)

                    # Register the repository manually into the domain registry
                    # This is necessary to ensure the repository is available for the outbox class
                    # Add repository to registry
                    self.register(new_repo_cls, internal=True, part_of=new_cls)
                    # Connect the explicitly defined repository to the outbox class
                    self.providers._register_repository(
                        new_cls, new_repo_cls
                    )  # Associate

                    outbox_repo = self.repository_for(new_cls)

                    # Store the repository for later use
                    self._outbox_repos[provider_name] = outbox_repo

                except Exception as e:
                    raise ConfigurationError(
                        f"Failed to initialize outbox for provider '{provider_name}': {str(e)}"
                    )
        else:
            # No providers configured - outbox repositories will be created lazily when needed
            logger.debug(
                "No providers configured during domain initialization. Outbox repositories will be created lazily."
            )

    def _get_outbox_repo(self, provider_name: str):
        """Get outbox repository for a specific provider."""
        # This check is largely unnecessary because `domain.init()` is mandatory,
        #   and it initializes the outbox repositories.
        #   This is largely a safeguard for tests to execute without calling `domain.init()`.
        if not self._outbox_repos:
            self._initialize_outbox()

        return self._outbox_repos[provider_name]

    # ------------------------------------------------------------------
    # Public database lifecycle API
    # ------------------------------------------------------------------

    def setup_database(self) -> None:
        """Create all database tables (aggregates, entities, projections, outbox).

        Must be called after ``domain.init()`` and within ``domain.domain_context()``.
        Delegates to each provider's ``_create_database_artifacts()`` which is
        idempotent — existing tables are left untouched.
        """
        for _, provider in self.providers.items():
            provider._create_database_artifacts()

    def setup_outbox(self) -> None:
        """Create only outbox tables.

        Useful when migrating from event-store to stream subscriptions where
        aggregate tables already exist.  Must be called after ``domain.init()``
        and within ``domain.domain_context()``.

        Raises :class:`~protean.exceptions.ConfigurationError` if the outbox
        is not enabled.
        """
        if not self.has_outbox:
            raise ConfigurationError(
                "Outbox is not enabled. Set "
                "'server.default_subscription_type = \"stream\"' "
                "in your domain configuration."
            )
        # Force DAO creation for outbox repos, then create pending tables
        for _provider_name, outbox_repo in self._outbox_repos.items():
            outbox_repo._dao  # noqa: B018
        for _, provider in self.providers.items():
            provider._create_database_artifacts()  # Idempotent

    def truncate_database(self) -> None:
        """Delete all rows from every table without dropping the tables.

        Clears aggregate/projection tables in all providers and the event
        store messages table.  Useful for resetting development data while
        preserving the schema.

        Broker state (Redis streams) is not cleared — streams are transient
        and will drain naturally.  This allows truncation while engines are
        still running.

        Must be called after ``domain.init()`` and within
        ``domain.domain_context()``.
        """
        # Ensure provider metadata is populated (idempotent — no-op if tables exist)
        self.setup_database()

        for _, provider in self.providers.items():
            provider._data_reset()

        self.event_store.store._data_reset()

    def drop_database(self) -> None:
        """Drop all database tables.

        Must be called after ``domain.init()`` and within
        ``domain.domain_context()``.
        """
        for _, provider in self.providers.items():
            provider._drop_database_artifacts()
