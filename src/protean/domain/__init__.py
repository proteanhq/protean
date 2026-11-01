"""This module implements the central domain object, along with decorators
to register Domain Elements.

Architecture
~~~~~~~~~~~~

The ``Domain`` class is the **composition root** of a Protean application.
Every domain element (aggregates, entities, commands, events, handlers, etc.)
is registered with, and orchestrated by, a single ``Domain`` instance.

**Composition over Inheritance**

Rather than packing all logic into a single monolithic class, ``Domain``
follows the *composition* pattern: cohesive groups of internal behavior are
extracted into dedicated helper classes that ``Domain`` owns and delegates to.
This keeps each class focused on a single responsibility (SRP) while
``Domain`` remains the stable public facade.

Current composed helpers:

* ``CommandProcessor``: Enriches, deduplicates, and dispatches commands
  to their handlers.  (``command_processor.py``)
* ``HandlerConfigurator``: Wires ``@handle`` / ``@read`` decorated methods
  into handler maps for command handlers, event handlers, projectors,
  process managers, and query handlers.  (``handler_setup.py``)
* ``InfrastructureManager``: Manages database and outbox lifecycle (setup,
  truncate, drop).  (``infrastructure.py``)
* ``QueryProcessor``: Dispatches queries to their registered handlers.
  (``query_processor.py``)
* ``ElementResolver``: Resolves string-based references between domain
  elements and assigns aggregate clusters.  (``resolver.py``)
* ``TypeManager``: Assigns type strings to events/commands, manages
  upcaster chains, fact events, and external event registration.
  (``type_manager.py``)
* ``DomainValidator``: Validates domain configuration, checks for
  unresolved references, and warns about missing handlers.
  (``validation.py``)

Each helper receives a reference to the ``Domain`` instance at construction
time and accesses the domain's registry, config, and other state through
that reference.  The ``Domain`` class retains thin delegate methods (e.g.
``_setup_command_handlers``) so that existing tests and call sites continue
to work without modification.

Supporting classes (in the same package):

* ``_DomainRegistry``: Element catalog keyed by type and FQN (``registry.py``)
* ``Config2``: TOML-based configuration with env-var substitution (``config.py``)
* ``DomainContext``: Thread-local context binding (``context.py``)
"""

import importlib.util
import inspect
import logging
import os
import pathlib
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    TypeVar,
    cast,
    dataclass_transform,
    overload,
)

if TYPE_CHECKING:
    from types import FrameType

    from protean.port.cache import BaseCache
    from protean.port.event_store import BaseEventStore
    from protean.utils.outbox import OutboxRepository
    from protean.utils.projection_rebuilder import RebuildResult
    from protean.utils.upcasting import UpcasterChain

from inflection import parameterize, titleize, transliterate, underscore

from protean.adapters import Brokers, Caches, Providers
from protean.adapters.event_store import EventStore
from protean.core.aggregate import aggregate_factory
from protean.core.application_service import application_service_factory
from protean.core.command import BaseCommand, command_factory
from protean.core.command_handler import BaseCommandHandler, command_handler_factory
from protean.core.database_model import BaseDatabaseModel, database_model_factory
from protean.core.domain_service import domain_service_factory
from protean.core.entity import entity_factory
from protean.core.event import BaseEvent, domain_event_factory
from protean.core.event_handler import event_handler_factory
from protean.core.event_sourced_repository import event_sourced_repository_factory
from protean.core.process_manager import process_manager_factory
from protean.core.projection import BaseProjection, projection_factory
from protean.core.projector import projector_factory
from protean.core.query import BaseQuery, query_factory
from protean.core.query_handler import query_handler_factory
from protean.core.repository import BaseRepository, repository_factory
from protean.core.subscriber import subscriber_factory
from protean.core.upcaster import BaseUpcaster, upcaster_factory
from protean.core.value_object import value_object_factory
from protean.core.view import ReadView
from protean.domain.registry import DomainRecord, _DomainRegistry
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import (
    Auto,
    Boolean,
    Date,
    DateTime,
    Float,
    HasMany,
    HasOne,
    Identifier,
    Integer,
    Reference,
    Status,
    String,
    Text,
    ValueObject,
)
from protean.fields import (
    Dict as DictField,
)
from protean.fields import (
    List as ListField,
)
from protean.fields.basic import ValueObjectList
from protean.integrations.logging import (
    OTelTraceContextFilter,
    ProteanCorrelationFilter,
    protean_correlation_processor,
    protean_otel_processor,
)
from protean.ir.builder import (
    IRBuilder,
    validate_lint_suppressions,
    validate_lint_table,
)
from protean.ir.diagnostics import DiagnosticCode
from protean.port.event_store import CausationNode
from protean.server.tracing import TraceEmitter
from protean.utils import (
    Clock,
    DomainObjects,
    SystemClock,
    fqn,
)
from protean.utils import (
    Processing as Processing,
)
from protean.utils.container import Element
from protean.utils.idempotency import IdempotencyStore
from protean.utils.logging import (
    TailSamplingFilter,
    TailSamplingProcessor,
    _install_root_filter,
    _move_redaction_filter_last,
    access_logger,
    configure_logging,
)
from protean.utils.projection_rebuilder import (
    rebuild_all_projections,
    rebuild_projection,
)
from protean.utils.reflection import declared_fields, has_fields
from protean.utils.telemetry import (
    get_meter,
    get_tracer,
    init_telemetry,
)

from .command_processor import CommandProcessor
from .config import Config2, ConfigAttribute
from .context import DomainContext, _DomainContextGlobals
from .handler_setup import HandlerConfigurator
from .infrastructure import InfrastructureManager
from .query_processor import QueryProcessor
from .resolver import ElementResolver
from .type_manager import TypeManager
from .validation import DomainValidator

logger = logging.getLogger(__name__)

# Field specifiers for ``@dataclass_transform()`` tell type-checkers which
# callables represent field declarations in class bodies using annotation
# syntax. mypy requires the ``field_specifiers`` argument to be a tuple
# literal at each decorator call site (it cannot be a shared module-level
# name), so the tuple is inlined on every element decorator below rather
# than referenced through a constant.

_T = TypeVar("_T")

# Binds a query's declared result type so ``dispatch`` returns it at the call
# site (see the ``dispatch`` overloads and ``BaseQuery``'s ``TResult``).
_QueryResult = TypeVar("_QueryResult")

# Binds the projection class passed to ``view_for`` so its reads return it.
_ProjectionT = TypeVar("_ProjectionT", bound=BaseProjection)

# a singleton sentinel value for parameter defaults
_sentinel = object()


class _Closeable(Protocol):
    """Structural type for infrastructure adapters that can be closed."""

    def close(self) -> None: ...


class Domain:
    """The registry for a domain's elements and the access point to its adapters.

    Create one ``Domain`` in your main module or in your package's
    ``__init__.py``::

        from protean import Domain
        domain = Domain()

    You can also set the root path explicitly::

        domain = Domain(root_path="/path/to/domain")

    The root path is the first of these that is set:

    1. The ``root_path`` argument.
    2. The ``DOMAIN_ROOT_PATH`` environment variable.
    3. The folder of the file that created the domain.
    4. The current working directory.

    Args:
        root_path: The folder that holds the domain file.
        name: The domain's name. Defaults to the calling module's name.
        config: Configuration values that override the defaults.
        identity_function: A function that generates identities for domain
            objects.
    """

    from protean.utils import IdentityStrategy, IdentityType  # noqa: PLC0415

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

    def _is_interactive_context(self, filename: str | None) -> bool:
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
        except ValueError:
            # The call stack is not that deep
            return str(Path.cwd())
        filename = frame.f_code.co_filename

        # Handle special cases
        if self._is_interactive_context(filename):
            # Interactive shell or Jupyter notebook
            return str(Path.cwd())

        # Handle frozen applications (PyInstaller, etc.)
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            return str(sys._MEIPASS)

        # Regular Python script
        try:
            return str(Path(filename).resolve().parent)
        # A NUL byte in the filename raises ValueError. A symlink loop raises
        # RuntimeError before Python 3.13. OSError is left out: a deleted working
        # directory raises it here and in Path.cwd() alike, so no fallback works.
        except (TypeError, ValueError, RuntimeError):
            # Fallback to CWD if unable to determine path
            return str(Path.cwd())

    def __init__(
        self,
        root_path: str | None = None,
        name: str = "",
        config: dict[str, Any] | None = None,
        identity_function: Callable[..., Any] | None = None,
    ) -> None:
        self.root_path: str
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

        # Registry for all domain Objects
        self._domain_registry = _DomainRegistry()

        #: The configuration dictionary as ``Config``.  This behaves
        #: exactly like a regular dictionary but supports additional methods
        #: to load a config from files.
        self.config: Config2 = self.load_config(config)

        # The function to invoke to generate identity
        self._identity_function = identity_function

        # Injectable source of "now" for deadline, lock, and retry-backoff time
        # comparisons, and for the stamps those comparisons read later (such as
        # outbox and idempotency-marker timestamps). Defaults to real UTC; tests
        # assign a stub clock to make boundary behavior deterministic. See
        # :class:`protean.utils.Clock`.
        self.clock: Clock = SystemClock()

        self.providers: Providers = Providers(self)
        self.event_store: EventStore = EventStore(self)
        self.brokers: Brokers = Brokers(self)
        self.caches: Caches = Caches(self)

        # Cache for holding Model to Entity/Aggregate associations.
        # Structure mirrors Providers._repositories: keyed by the element's
        # fully qualified name, then by database type. A model registered
        # with database=None sits under the None key and is the fallback for
        # any provider.
        self._database_models: dict[str, dict[str | None, type[BaseDatabaseModel]]] = (
            defaultdict(dict)
        )
        self._constructed_models: dict[str, BaseDatabaseModel] = {}

        # Message enricher hooks — callables that add custom metadata to events/commands.
        # Event enrichers receive (event, aggregate) and return dict[str, Any].
        # Command enrichers receive (command,) and return dict[str, Any].
        # Results are merged into metadata.extensions.
        self._event_enrichers: list[Callable[..., Any]] = []
        self._command_enrichers: list[Callable[..., Any]] = []
        # Aggregate pre-persist enrichers receive (aggregate,) and mutate it
        # in place to stamp cross-cutting lifecycle/audit fields on save.
        self._aggregate_enrichers: list[Callable[..., Any]] = []

        # Composed helpers — see handler_setup.py, validation.py, etc.
        self._command_processor = CommandProcessor(self)
        self._handler_configurator = HandlerConfigurator(self)
        self._infrastructure = InfrastructureManager(self)
        self._query_processor = QueryProcessor(self)
        self._resolver = ElementResolver(self)
        self._type_manager = TypeManager(self)
        self._validator = DomainValidator(self)

        #: A list of functions that are called when the domain context
        #: is destroyed.  This is the place to store code that cleans up and
        #: disconnects from databases, for example.
        self.teardown_domain_context_functions: list[Callable[..., Any]] = []

        # Placeholder array for resolving classes referenced by domain elements
        self._pending_class_resolutions: dict[str, Any] = defaultdict(list)

        # Partition-per-key routing map (ADR-0028): stream_category ->
        # partition-key field name. Built by ``HandlerConfigurator`` during
        # ``_prepare()`` from every handler that declares ``sequential_by``, and
        # read by the Unit of Work at commit to denormalize the key onto each
        # outbox row. Empty when no handler opts in.
        self._partition_keys: dict[str, str] = {}

        # Event classes that have already emitted a raise-time deprecation
        # warning, so a deprecated event warns once per type, not per instance.
        self._deprecated_events_warned: set[type] = set()

        # Lazy-initialized idempotency store
        self._idempotency_store: IdempotencyStore | None = None

        # Lazy-initialized trace emitter for command processing observability
        self._trace_emitter: TraceEmitter | None = None

        # Lazy-initialized OpenTelemetry providers (set by init_telemetry)
        self._otel_tracer_provider: Any = None
        self._otel_meter_provider: Any = None
        self._otel_init_attempted = False

    # ------------------------------------------------------------------
    # Property proxies for composed helper state (backward compatibility)
    # ------------------------------------------------------------------

    @property
    def _events_and_commands(
        self,
    ) -> dict[str, type[BaseCommand] | type[BaseEvent]]:
        return self._type_manager.events_and_commands

    @property
    def _upcasters(self) -> list[type[BaseUpcaster]]:
        return self._type_manager.upcasters

    @property
    def _upcaster_chain(self) -> "UpcasterChain":
        return self._type_manager.upcaster_chain

    @property
    def _outbox_repos(self) -> dict[str, BaseRepository]:
        return self._infrastructure.outbox_repos

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
    def has_idempotent_consumers(self) -> bool:
        """Whether any registered projector opts into consume-side idempotency.

        Gates creation of the per-provider ``ProcessedMessage`` marker table so
        domains that don't use ``idempotent=True`` projectors pay nothing.
        """
        return any(
            getattr(record.cls.meta_, "idempotent", False)
            for record in self.registry.projectors.values()
        )

    @property
    def idempotency_store(self) -> IdempotencyStore:
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
    def trace_emitter(self) -> TraceEmitter:
        """Lazily initialize and return a TraceEmitter for command tracing.

        Used by CommandProcessor to emit handler.started/completed/failed
        traces during synchronous command processing, making commands visible
        in the Observatory dashboard.
        """
        if self._trace_emitter is None:
            observatory_config = self.config.get("observatory", {})
            try:
                trace_retention_days = int(
                    observatory_config.get("trace_retention_days", 7)
                )
            except (AttributeError, OverflowError, TypeError, ValueError):
                # ``AttributeError``: ``observatory`` is not a table.
                # ``OverflowError``: the retention is ``inf``.
                trace_retention_days = 7
            self._trace_emitter = TraceEmitter(
                self, trace_retention_days=trace_retention_days
            )
        return self._trace_emitter

    @property
    def tracer(self) -> Any:
        """Return an OpenTelemetry ``Tracer`` for this domain.

        Lazy-initializes the telemetry providers on first access when
        telemetry is enabled. Returns a no-op tracer when telemetry is
        disabled or the ``opentelemetry`` packages are not installed.
        """
        if not self._otel_init_attempted:
            init_telemetry(self)
        return get_tracer(self)

    @property
    def meter(self) -> Any:
        """Return an OpenTelemetry ``Meter`` for this domain.

        Lazy-initializes the telemetry providers on first access when
        telemetry is enabled. Returns a no-op meter when telemetry is
        disabled or the ``opentelemetry`` packages are not installed.
        """
        if not self._otel_init_attempted:
            init_telemetry(self)
        return get_meter(self)

    @property
    @lru_cache
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
    @lru_cache
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

    def _prepare(self, traverse: bool = True, validate: bool = True) -> None:
        """Resolve references, wire handlers, and optionally validate.

        This is the shared preparation sequence used by both [`init`][protean.domain.Domain.init]
        (which validates fail-fast and initializes adapters) and `check`
        (which skips fail-fast validation and uses ``validate_all()`` instead).

        Args:
            traverse: Whether to auto-discover domain elements from files.
            validate: Whether to run fail-fast validation at the end.
                Set to ``False`` when the caller will run ``validate_all()``
                separately (e.g. `check`).
        """
        if traverse is True:
            self._traverse()

        # Resolve all pending references
        self._resolve_references()

        # Fail fast if any references remain unresolved — later steps
        # (e.g. _assign_aggregate_clusters) assume resolved classes.
        self._check_for_unresolved_references()

        # Assign Aggregate Clusters
        self._assign_aggregate_clusters()

        # Set Aggregate Cluster Options
        self._set_aggregate_cluster_options()

        # Generate Fact Event Classes
        self._generate_fact_event_classes()

        # Generate and set event/command `__type__` value
        self._set_and_record_event_and_command_type()

        # Build the runtime upcaster chain (used during deserialization).
        # Gated on `validate` so check() (validate=False) skips the runtime
        # build; check() instead validates a throwaway chain via
        # DomainValidator.validate_all(), reporting a malformed chain as a
        # structured error rather than crashing.
        if validate:
            self._build_upcaster_chains()

        # Parse and setup handler methods in Command Handlers
        self._setup_command_handlers()

        # Parse and setup handler methods in Event Handlers
        self._setup_event_handlers()

        # Parse and setup handler methods in Projectors
        self._setup_projectors()

        # Parse and setup handler methods in Process Managers
        self._setup_process_managers()

        # Generate and set query `__type__` value
        self._set_query_type()

        # Parse and setup handler methods in Query Handlers
        self._setup_query_handlers()

        # Validate sequential_by handlers and build the partition-key map
        # (field existence + one-key-per-category). Broker-capability gating is
        # deferred to init() where adapters are live.
        self._handler_configurator.validate_sequential_by()

        # Run fail-fast validations (skipped by check())
        if validate:
            self._validate_domain()

    def init(self, traverse: bool = True) -> None:
        """Load the domain's elements, validate them, and initialize its adapters.

        Before loading, ``init`` configures logging with ``configure_logging()``.
        It skips this when the root logger already has handlers or when the
        ``PROTEAN_NO_AUTO_LOGGING`` environment variable is ``1`` or ``true``
        in any case. A failure in this step does not stop ``init``.

        Args:
            traverse: Import every module in the domain file's folder and its
                subfolders, so their elements register. With ``False``, an
                element registers only when your code imports its module, so
                import subscribers and event handlers where the domain runs.
        """
        self._auto_configure_logging()

        self._prepare(traverse=traverse)

        # Initialize adapters after loading domain
        self._initialize()

        # An identity a SQL column cannot hold (an integer under the uuid
        # strategy overflows every SQL integer column) would only fail on the
        # first save; needs live providers, so it runs after _initialize().
        self.providers.validate_identity_capacity()

        # Gate sequential_by handlers on broker STREAM_PARTITIONING support
        # (ADR-0028); needs live brokers, so it runs after _initialize().
        self._handler_configurator.validate_sequential_by_capabilities()

        # Initialize outbox DAOs for all providers
        if self.has_outbox:
            self._initialize_outbox()

        # Initialize consume-side idempotency markers when any projector opts in
        if self.has_idempotent_consumers:
            self._initialize_processed_messages()

    def _auto_configure_logging(self) -> None:
        """Auto-configure logging during ``Domain.init()``.

        Guardrails:

        - **Escape hatch:** If ``PROTEAN_NO_AUTO_LOGGING=1`` is set, skip entirely.
        - **Idempotency:** If the root logger already has handlers, skip.
          The user has already configured logging.
        - **Non-fatal:** Any exception is caught and reported to stderr so that
          ``Domain.init()`` never fails due to logging misconfiguration.
        """
        try:
            if os.environ.get("PROTEAN_NO_AUTO_LOGGING", "").lower() in (
                "1",
                "true",
            ):
                return

            root = logging.getLogger()
            if root.handlers:
                logger.debug(
                    "Skipping auto logging configuration: "
                    "root logger already has handlers"
                )
                return

            self.configure_logging()
        except Exception as exc:  # noqa: BLE001 - logging is broken, so warn on stderr
            # Degrade gracefully — never let logging setup break Domain.init()
            print(
                f"Warning: auto-configuration of logging failed: {exc}",
                file=sys.stderr,
            )

    def check(self, traverse: bool = True) -> dict[str, Any]:
        """Validate the domain and return a diagnostic report.

        ``check`` loads and validates the domain without initializing adapters.
        It collects every validation error instead of stopping at the first.
        When there are no errors, it also reports the IR diagnostics, such as
        ``UNHANDLED_EVENT``.

        When ``traverse`` is true but ``root_path`` names neither a directory
        nor a file (``Domain(__name__)`` passes a module name), the domain is
        checked without traversal and a warning is logged.

        Args:
            traverse: Import every module under the domain folder, as
                [`init`][protean.domain.Domain.init] does.

        Returns:
            A dict of this shape::

                {
                    "domain": "<domain name>",
                    "status": "pass" | "warn" | "info" | "fail",
                    "errors": [...],
                    "diagnostics": [...],  # empty when there are errors
                    "counts": {
                        "errors": int,
                        "warnings": int,
                        "infos": int,
                    },
                }

            Each diagnostic has a ``level`` of ``"warning"`` or ``"info"``,
            which sets the counts and the overall ``status``. Any error makes
            the status ``"fail"``. A failure to build the IR becomes one entry
            in ``errors``, with ``element`` set to ``"to_ir"`` and ``code`` set
            to the exception class name.

        Raises:
            ConfigurationError: If the ``[lint]`` table holds a value the IR
                builder rejects, such as ``rules = 5``. This holds even when
                validation errors skip the IR build.
        """
        if traverse and not self._root_dir().is_dir():
            # ``Domain(__name__)`` passes a module name as ``root_path``, which
            # names no directory, so ``_traverse`` would fail on ``os.listdir``.
            logger.warning(
                "Root path '%s' of domain '%s' is not a directory or file; "
                "checking the domain without traversal",
                self.root_path,
                self.name,
            )
            traverse = False

        self._prepare(traverse=traverse, validate=False)

        # Run the collect-all validator (does not raise)
        self._validator.validate_all()

        errors = self._validator.errors
        diagnostics: list[dict[str, str]] = []

        # Check ``[lint]`` before the IR short-circuit below, so a malformed
        # value raises even when validation errors skip the IR build.
        lint_config = self.config.get("lint", {})
        lint_error = validate_lint_table(lint_config) or validate_lint_suppressions(
            lint_config.get("suppressions", {})
        )
        if lint_error:
            raise ConfigurationError(lint_error)

        # Build IR for additional diagnostics only if no fatal errors
        if not errors:
            try:
                ir = self.to_ir()
                diagnostics = ir.get("diagnostics", [])
            # A failed IR build is a finding, so the check fails with it as an
            # error. No ``exc_info``: the CLI logs at DEBUG by default in
            # development, so even a DEBUG traceback would reach the user.
            except Exception as exc:  # noqa: BLE001 - IR build runs over user elements
                logger.warning(
                    "Could not build the IR for domain '%s': %s: %s",
                    self.name,
                    type(exc).__name__,
                    exc,
                )
                errors.append(
                    {
                        "code": type(exc).__name__,
                        "element": "to_ir",
                        "level": "error",
                        "message": f"Could not build the IR: {type(exc).__name__}: {exc}",
                    }
                )

        total_errors = len(errors)
        total_warnings = sum(1 for d in diagnostics if d.get("level") == "warning")
        total_infos = sum(1 for d in diagnostics if d.get("level") == "info")

        if total_errors > 0:
            status = "fail"
        elif total_warnings > 0:
            status = "warn"
        elif total_infos > 0:
            status = "info"
        else:
            status = "pass"

        return {
            "domain": self.name,
            "status": status,
            "errors": errors,
            "diagnostics": diagnostics,
            "counts": {
                "errors": total_errors,
                "warnings": total_warnings,
                "infos": total_infos,
            },
        }

    def _root_dir(self) -> Path:
        """The directory ``_traverse`` walks: ``root_path`` itself, or its
        parent when ``root_path`` is a file (e.g. from ``__file__``)."""
        root_path = Path(self.root_path)
        return root_path.parent if root_path.is_file() else root_path

    def _traverse(self) -> None:
        root_dir = self._root_dir()

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
        # Sorted so modules load, and enrichers register, in the same order
        # on every filesystem. `os.listdir` returns entries in arbitrary order.
        subdirectories = [
            name
            for name in sorted(os.listdir(root_dir))
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
            for filename in sorted(os.listdir(directory)):
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
                    assert spec is not None and spec.loader is not None
                    module = importlib.util.module_from_spec(spec)

                    # Register in sys.modules before execution to prevent
                    # duplicate loading if another module imports this one
                    # during execution (e.g., circular or relative imports).
                    if module.__name__ not in sys.modules:
                        sys.modules[module.__name__] = module
                        spec.loader.exec_module(module)

                    logger.debug(f"Loaded {filename}")

    def _is_domain_file(self, file_path: str) -> bool:
        """Check if this is the domain file itself, to avoid self-import.

        This replaces the direct path comparison that was used before.
        """
        if not Path(file_path).is_file():
            return False

        # Get the frame where the Domain was instantiated
        frame: FrameType | None = sys._getframe(0)
        while frame:
            if frame.f_code.co_filename == file_path:
                return True
            frame = frame.f_back

        return False

    def _initialize(self) -> None:
        """Initialize domain dependencies and adapters."""
        self.providers._initialize()
        self.caches._initialize()
        self.brokers._initialize()
        self.event_store._initialize()

    def close(self) -> None:
        """Close all domain infrastructure connections and release resources.

        Shuts down adapters in reverse initialization order so that
        dependents close before their dependencies.
        Repeated calls delegate to the underlying adapters; each registry
        guards against double-close but behavior depends on individual
        adapter implementations.
        """
        logger.info("Closing domain infrastructure...")

        closeables: list[tuple[str, _Closeable]] = [
            ("event store", self.event_store),
            ("brokers", self.brokers),
            ("caches", self.caches),
            ("providers", self.providers),
        ]
        for name, closeable in closeables:
            try:
                closeable.close()
            except Exception:  # one failed close must not skip the rest; logged
                logger.exception("Error closing %s", name)

        logger.info("Domain infrastructure closed")

    def load_config(self, config: dict[str, Any] | None = None) -> Config2:
        """Load configuration from a dict or a .toml file."""
        config_obj: Config2
        if config is not None:
            config_obj = Config2.load_from_dict(config)
        else:
            config_obj = Config2.load_from_path(self.root_path)

        # Load Constants
        if "custom" in config_obj:
            for constant, value in config_obj["custom"].items():
                setattr(self, constant, value)

        return config_obj

    def domain_context(self, **kwargs: Any) -> DomainContext:
        """Create a ``DomainContext``. Use as a ``with``
        block to push the context, which will make ``current_domain``
        point at this domain.

        ::

            with domain.domain_context():
                init_db()
        """
        return DomainContext(self, **kwargs)

    def teardown_domain_context(self, f: Callable[..., Any]) -> Callable[..., Any]:
        """Register a function to call when a domain context ends.

        The function runs when a ``with domain.domain_context():`` block exits,
        or when ``ctx.pop()`` is called, just before the context leaves the
        stack. It receives the unhandled exception that ended the context, or
        ``None``.

        Returns:
            The function unchanged, so this works as a decorator::

                @domain.teardown_domain_context
                def close_connections(exc):
                    ...
        """
        self.teardown_domain_context_functions.append(f)
        return f

    def do_teardown_domain_context(self, exc: Any = _sentinel) -> None:
        """Called right before the domain context is popped.

        This calls all functions decorated with
        ``teardown_domain_context``.

        This is called by
        ``DomainContext.pop()``.
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        for func in reversed(self.teardown_domain_context_functions):
            func(exc)

    def __str__(self) -> str:
        return f"Domain: {self.name}"

    @property
    @lru_cache
    def registry(self) -> _DomainRegistry:
        return self._domain_registry

    def factory_for(self, domain_object_type: DomainObjects) -> Callable[..., Any]:
        factories: dict[str, Callable[..., Any]] = {
            DomainObjects.AGGREGATE.value: aggregate_factory,
            DomainObjects.APPLICATION_SERVICE.value: application_service_factory,
            DomainObjects.COMMAND.value: command_factory,
            DomainObjects.COMMAND_HANDLER.value: command_handler_factory,
            DomainObjects.EVENT.value: domain_event_factory,
            DomainObjects.EVENT_HANDLER.value: event_handler_factory,
            DomainObjects.EVENT_SOURCED_REPOSITORY.value: event_sourced_repository_factory,
            DomainObjects.DOMAIN_SERVICE.value: domain_service_factory,
            DomainObjects.ENTITY.value: entity_factory,
            DomainObjects.DATABASE_MODEL.value: database_model_factory,
            DomainObjects.PROCESS_MANAGER.value: process_manager_factory,
            DomainObjects.REPOSITORY.value: repository_factory,
            DomainObjects.SUBSCRIBER.value: subscriber_factory,
            DomainObjects.VALUE_OBJECT.value: value_object_factory,
            DomainObjects.PROJECTION.value: projection_factory,
            DomainObjects.PROJECTOR.value: projector_factory,
            DomainObjects.QUERY.value: query_factory,
            DomainObjects.QUERY_HANDLER.value: query_handler_factory,
            DomainObjects.UPCASTER.value: upcaster_factory,
        }

        if domain_object_type.value not in factories:
            raise IncorrectUsageError(
                f"Unknown Element Type `{domain_object_type.value}`",
                code=DiagnosticCode.USAGE_UNKNOWN_ELEMENT_TYPE,
                location="Domain.factory_for",
            )

        return factories[domain_object_type.value]

    def _file_database_model(self, model_cls: type[BaseDatabaseModel]) -> None:
        """Record a database model against its target and database type.

        ``meta_.part_of`` must already be a class.

        Raises:
            IncorrectUsageError: When a model for the same target and
                database type is already recorded.
        """
        entity_key = fqn(model_cls.meta_.part_of)
        db_key = model_cls.meta_.database  # e.g., "postgresql", "sqlite", or None
        if db_key in self._database_models[entity_key]:
            raise IncorrectUsageError(
                f"A database model for `{model_cls.meta_.part_of.__name__}` "
                f"targeting database `{db_key}` is already registered",
                code=DiagnosticCode.USAGE_DUPLICATE_DATABASE_MODEL,
                location="Domain._register_element",
            )
        self._database_models[entity_key][db_key] = model_cls

    def _register_element(
        self,
        element_type: DomainObjects,
        element_cls: type[_T],
        internal: bool = False,
        auto_generated: bool = False,
        **opts: Any,
    ) -> type[_T]:
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
        # The factory returns the enriched, registered element class. It is
        # genuinely untyped (Any) — the concrete class carries framework
        # attributes (``meta_``, ``element_type``) injected at registration
        # that are not visible on the bare ``type[_T]`` type parameter, so we
        # treat it as Any internally and re-narrow to ``type[_T]`` at return.
        new_cls: Any = factory(element_cls, self, **opts)

        # A string ``part_of`` is filed once ``domain.init()`` resolves it.
        if element_type == DomainObjects.DATABASE_MODEL and not isinstance(
            new_cls.meta_.part_of, str
        ):
            self._file_database_model(new_cls)

        # Register element with domain
        self._domain_registry.register_element(new_cls, internal, auto_generated)

        # Resolve or record elements to be resolved

        # 1. Associations
        if has_fields(new_cls):
            for field_obj in declared_fields(new_cls).values():
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

            # Also scan FieldSpec metadata for ValueObject descriptors, such
            # as a List whose content_type is a ValueObject
            field_meta = getattr(new_cls, "__protean_field_meta__", {})
            for spec in field_meta.values():
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
            DomainObjects.DATABASE_MODEL,
            DomainObjects.REPOSITORY,
            DomainObjects.EVENT_SOURCED_REPOSITORY,
            DomainObjects.VALUE_OBJECT,
        ] and isinstance(new_cls.meta_.part_of, str):
            self._pending_class_resolutions[new_cls.meta_.part_of].append(
                ("AggregateCls", (new_cls))
            )

        if element_type == DomainObjects.PROJECTOR and isinstance(
            new_cls.meta_.projector_for, str
        ):
            self._pending_class_resolutions[new_cls.meta_.projector_for].append(
                ("ProjectionCls", (new_cls))
            )

        if element_type == DomainObjects.QUERY and isinstance(
            new_cls.meta_.part_of, str
        ):
            self._pending_class_resolutions[new_cls.meta_.part_of].append(
                ("QueryProjectionCls", (new_cls))
            )

        if element_type == DomainObjects.QUERY_HANDLER and isinstance(
            new_cls.meta_.part_of, str
        ):
            self._pending_class_resolutions[new_cls.meta_.part_of].append(
                ("QueryHandlerProjectionCls", (new_cls))
            )

        return cast("type[_T]", new_cls)

    def _resolve_references(self) -> None:
        """Resolve pending class references in association fields."""
        self._resolver.resolve_references()

    # _cls should never be specified by keyword, so start it with an
    # underscore.  The presence of _cls is used to detect if this
    # decorator is being called with parameters or not.
    def _domain_element(
        self,
        element_type: DomainObjects,
        _cls: type[_T] | None = None,
        internal: bool = False,
        **kwargs: Any,
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        """Returns the registered class after decorating it and recording its presence in the domain"""

        def wrap(cls: type[_T]) -> type[_T]:
            return self._register_element(element_type, cls, internal, **kwargs)

        # See if we're being called as @Entity or @Entity().
        if _cls is None:
            # We're called with parens.
            return wrap

        # We're called as @dataclass without parens.
        return wrap(_cls)

    def register_database_model(
        self, database_model_cls: type[_T], internal: bool = False, **kwargs: Any
    ) -> type[_T]:
        """Register a model class"""
        return self._register_element(
            DomainObjects.DATABASE_MODEL, database_model_cls, internal, **kwargs
        )

    def register(
        self,
        element_cls: Any,
        internal: bool = False,
        auto_generated: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Register an element with the domain.

        Returns the fully-formed domain element, subclassed and associated with
        all traits necessary for its element type.
        """

        # Reject unknown Domain Elements, identified by the absence of `element_type` class var
        if getattr(element_cls, "element_type", None) not in list(DomainObjects):
            raise NotSupportedError(
                f"Element `{element_cls.__name__}` is not a valid element class",
                code=DiagnosticCode.UNSUPPORTED_ELEMENT_CLASS,
                location="Domain.register",
            )

        return self._register_element(
            element_cls.element_type, element_cls, internal, auto_generated, **kwargs
        )

    def fetch_element_cls_from_registry(
        self, element: str, element_types: tuple[DomainObjects, ...]
    ) -> "type[Element]":
        """Util Method to fetch an Element's class from its name"""
        try:
            # Try fetching by class name
            element_cls: type[Element] = self._get_element_by_name(
                element_types, element
            ).cls
            return element_cls
        except ConfigurationError:
            # Try fetching by fully qualified class name. This raises
            # ConfigurationError when the element has not been registered.
            fq_element_cls: type[Element] = self._get_element_by_fully_qualified_name(
                element_types, element
            ).cls
            return fq_element_cls

    def _get_element_by_name(
        self, element_types: tuple[DomainObjects, ...], element_name: str
    ) -> DomainRecord:
        """Fetch Domain record with the provided Element name"""
        try:
            elements = self._domain_registry._elements_by_name[element_name]
            allowed_types = [o.value for o in element_types]

            # Collect all elements matching the requested type(s)
            matching = [e for e in elements if e.class_type in allowed_types]

            if len(matching) == 1:
                return matching[0]
            elif len(matching) > 1:
                fq_names = ", ".join(e.qualname for e in matching)
                raise ConfigurationError(
                    {
                        "element": (
                            f"Multiple elements with name '{element_name}' registered in "
                            f"domain {self.name}: {fq_names}. "
                            "Use the fully qualified name to disambiguate."
                        )
                    },
                    code=DiagnosticCode.CONFIG_AMBIGUOUS_ELEMENT_NAME,
                    location="Domain._get_element_by_name",
                )
            else:
                raise ConfigurationError(
                    {
                        "element": f"Element {element_name} not registered in domain {self.name}"
                    },
                    code=DiagnosticCode.CONFIG_ELEMENT_NOT_REGISTERED,
                    location="Domain._get_element_by_name",
                )
        except KeyError as e:
            raise ConfigurationError(
                {
                    "element": f"Element {element_name} not registered in domain {self.name}"
                },
                code=DiagnosticCode.CONFIG_ELEMENT_NOT_REGISTERED,
                location="Domain._get_element_by_name",
            ) from e

    def _get_element_by_fully_qualified_name(
        self, element_types: tuple[DomainObjects, ...], element_fq_name: str
    ) -> DomainRecord:
        """Fetch Domain record with the Fully Qualified Element name"""
        for element_type in element_types:
            if element_fq_name in self._domain_registry._elements[element_type.value]:
                return self._domain_registry._elements[element_type.value][
                    element_fq_name
                ]
        raise ConfigurationError(
            {
                "element": f"Element {element_fq_name} not registered in domain {self.name}"
            },
            code=DiagnosticCode.CONFIG_ELEMENT_NOT_REGISTERED,
            location="Domain._get_element_by_fully_qualified_name",
        )

    def _get_element_by_class(
        self, element_types: tuple[DomainObjects, ...], element_cls: type
    ) -> DomainRecord:
        """Fetch Domain record with Element class details"""
        element_qualname = fqn(element_cls)
        return self._get_element_by_fully_qualified_name(
            element_types, element_qualname
        )

    def _replace_element_by_class(self, new_element_cls: type) -> None:
        aggregate_record = self._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY), new_element_cls
        )

        self._domain_registry._elements[aggregate_record.class_type][
            aggregate_record.qualname
        ].cls = new_element_cls

    def _check_for_unresolved_references(self) -> None:
        """Raise a ``ConfigurationError`` if any string references remain unresolved."""
        self._validator.check_unresolved_references()

    def _validate_domain(self) -> None:
        """Validate the domain for correctness, called just before activation."""
        self._validator.validate()

    def _assign_aggregate_clusters(self) -> None:
        """Assign Aggregate Clusters to all relevant elements."""
        self._resolver.assign_aggregate_clusters()

    def _set_aggregate_cluster_options(self) -> None:
        """Propagate aggregate-level options to child entities."""
        self._resolver.set_aggregate_cluster_options()

    def _set_and_record_event_and_command_type(self) -> None:
        self._type_manager.set_and_record_types()

    def _build_upcaster_chains(self) -> None:
        self._type_manager.build_upcaster_chains()

    def register_external_event(
        self, event_cls: type[BaseEvent], type_string: str
    ) -> None:
        """Register an external event with the domain.

        Maps an external event type string to an event class without
        adding it to the domain registry.
        """
        self._type_manager.register_external_event(event_cls, type_string)

    def _setup_command_handlers(self) -> None:
        self._handler_configurator.setup_command_handlers()

    def _setup_event_handlers(self) -> None:
        self._handler_configurator.setup_event_handlers()

    def _setup_projectors(self) -> None:
        self._handler_configurator.setup_projectors()

    def _setup_process_managers(self) -> None:
        self._handler_configurator.setup_process_managers()

    def _set_query_type(self) -> None:
        """Set ``__type__`` on registered queries so HandlerMixin._handle() can route them."""
        self._handler_configurator.set_query_type()

    def _setup_query_handlers(self) -> None:
        """Build the handler map for all registered query handlers."""
        self._handler_configurator.setup_query_handlers()

    def _generate_fact_event_classes(self) -> None:
        self._type_manager.generate_fact_event_classes()

    # ------------------------------------------------------------------
    # IR Generation
    # ------------------------------------------------------------------

    def to_ir(self) -> dict[str, Any]:
        """Build and return the Intermediate Representation for this domain.

        The domain must be initialised (``init()`` called) before invoking
        this method.
        """
        return IRBuilder(self).build()

    ######################
    # Element Decorators #
    ######################

    @overload
    def aggregate(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def aggregate(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def aggregate(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.AGGREGATE,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def application_service(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def application_service(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def application_service(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.APPLICATION_SERVICE,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def command(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def command(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def command(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.COMMAND,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def command_handler(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def command_handler(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def command_handler(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.COMMAND_HANDLER, _cls=_cls, **kwargs)

    @overload
    def event(self, _cls: type[_T], **kwargs: Any) -> type[_T]: ...  # pragma: no cover
    @overload
    def event(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def event(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.EVENT,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def event_handler(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def event_handler(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def event_handler(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.EVENT_HANDLER,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def domain_service(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def domain_service(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def domain_service(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.DOMAIN_SERVICE,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def entity(self, _cls: type[_T], **kwargs: Any) -> type[_T]: ...  # pragma: no cover
    @overload
    def entity(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def entity(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.ENTITY, _cls=_cls, **kwargs)

    @overload
    def database_model(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def database_model(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def database_model(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.DATABASE_MODEL, _cls=_cls, **kwargs)

    @overload
    def repository(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def repository(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def repository(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(DomainObjects.REPOSITORY, _cls=_cls, **kwargs)

    @overload
    def subscriber(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def subscriber(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def subscriber(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.SUBSCRIBER,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def value_object(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def value_object(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def value_object(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.VALUE_OBJECT,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def projection(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def projection(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def projection(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.PROJECTION,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def projector(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def projector(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def projector(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.PROJECTOR,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def query(self, _cls: type[_T], **kwargs: Any) -> type[_T]: ...  # pragma: no cover
    @overload
    def query(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def query(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.QUERY,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def query_handler(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def query_handler(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
    def query_handler(
        self, _cls: type[_T] | None = None, **kwargs: Any
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        return self._domain_element(
            DomainObjects.QUERY_HANDLER,
            _cls=_cls,
            **kwargs,
        )

    @overload
    def process_manager(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def process_manager(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...
    @dataclass_transform(
        field_specifiers=(
            Auto,
            Boolean,
            Date,
            DateTime,
            DictField,
            Float,
            HasMany,
            HasOne,
            Identifier,
            Integer,
            ListField,
            Reference,
            Status,
            String,
            Text,
            ValueObject,
        )
    )
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
    @overload
    def upcaster(
        self, _cls: type[_T], **kwargs: Any
    ) -> type[_T]: ...  # pragma: no cover
    @overload
    def upcaster(
        self, _cls: None = ..., **kwargs: Any
    ) -> Callable[[type[_T]], type[_T]]: ...  # pragma: no cover
    def upcaster(
        self,
        _cls: type[_T] | None = None,
        **kwargs: Any,
    ) -> type[_T] | Callable[[type[_T]], type[_T]]:
        """Register an event upcaster with the domain.

        Upcasters transform raw event payloads from an old schema version to
        a newer one.  They are applied lazily during deserialization so that
        ``@apply`` handlers and event handlers always see the current schema.

        Keyword Args:
            event_type (type): The event class this upcaster targets (current version).
            from_version (int): Source version number (e.g. ``1``).
            to_version (int): Target version number (e.g. ``2``).

        Example::

            @domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
            class UpcastOrderPlacedV1ToV2(BaseUpcaster):
                def upcast(self, data: dict) -> dict:
                    data["currency"] = "USD"
                    return data
        """
        return self._domain_element(
            DomainObjects.UPCASTER,
            _cls=_cls,
            **kwargs,
        )

    ########################
    # Message Enrichment  #
    ########################
    def register_event_enricher(self, fn: Callable[..., Any]) -> None:
        """Register a callable that enriches every event's metadata.

        The enricher is called during `raise_`
        with ``(event, aggregate)`` and must return a ``dict[str, Any]``
        whose entries are merged into ``metadata.extensions``.

        Enrichers execute in registration order (FIFO).  Later enrichers
        can overwrite keys set by earlier ones.  If an enricher raises an
        exception it propagates and the event is not appended.

        Args:
            fn: A callable with signature ``(event, aggregate) -> dict[str, Any]``.

        Example::

            def add_user_context(event, aggregate):
                return {"user_id": get_current_user_id()}

            domain.register_event_enricher(add_user_context)
        """
        if not callable(fn):
            raise IncorrectUsageError(
                "Event enricher must be callable",
                code=DiagnosticCode.USAGE_ENRICHER_NOT_CALLABLE,
                location="Domain.register_event_enricher",
            )
        self._event_enrichers.append(fn)

    @property
    def event_enricher(self) -> Callable[..., Any]:
        """Decorator form of `register_event_enricher`.

        Example::

            @domain.event_enricher
            def add_tenant(event, aggregate):
                return {"tenant_id": get_current_tenant_id()}
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register_event_enricher(fn)
            return fn

        return decorator

    def register_command_enricher(self, fn: Callable[..., Any]) -> None:
        """Register a callable that enriches every command's metadata.

        The enricher is called during `process` with ``(command,)``
        and must return a ``dict[str, Any]`` whose entries are merged into
        ``metadata.extensions``.

        Enrichers execute in registration order (FIFO).  Later enrichers
        can overwrite keys set by earlier ones.  If an enricher raises an
        exception it propagates and the command is not processed.

        Args:
            fn: A callable with signature ``(command,) -> dict[str, Any]``.

        Example::

            def add_request_context(command):
                return {"request_id": get_request_id()}

            domain.register_command_enricher(add_request_context)
        """
        if not callable(fn):
            raise IncorrectUsageError(
                "Command enricher must be callable",
                code=DiagnosticCode.USAGE_ENRICHER_NOT_CALLABLE,
                location="Domain.register_command_enricher",
            )
        self._command_enrichers.append(fn)

    @property
    def command_enricher(self) -> Callable[..., Any]:
        """Decorator form of `register_command_enricher`.

        Example::

            @domain.command_enricher
            def add_request_id(command):
                return {"request_id": get_request_id()}
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register_command_enricher(fn)
            return fn

        return decorator

    def register_aggregate_enricher(self, fn: Callable[..., Any]) -> None:
        """Register a callable that stamps fields on an aggregate just before
        it is saved.

        The enricher receives the aggregate and changes it in place. Its return
        value is ignored. It runs inside the domain context on every create and
        update through a repository, and for each row that ``query.update()``
        saves, so it can read the acting user from ``g``. It does not run for
        event-sourced aggregates, for a save that passes ``apply_hooks=False``,
        or for the framework's internal aggregates (outbox rows, the memory
        event store's messages, processed-message records).

        Enrichers run in registration order. If one raises, the exception
        propagates and the save is aborted. On an update, the version is
        rolled back.

        Use it only for lifecycle and audit fields such as ``updated_by`` and
        ``created_by``. Enforce invariants and raise events in the aggregate's
        own methods.

        Args:
            fn: A callable with signature ``(aggregate) -> None``.

        Example::

            @domain.aggregate_enricher
            def stamp_audit(aggregate):
                user = g.get("current_user")
                aggregate.updated_by = user
                if aggregate.created_by is None:
                    aggregate.created_by = user
        """
        if not callable(fn):
            raise IncorrectUsageError(
                "Aggregate enricher must be callable",
                code=DiagnosticCode.USAGE_ENRICHER_NOT_CALLABLE,
                location="Domain.register_aggregate_enricher",
            )
        self._aggregate_enrichers.append(fn)

    @property
    def aggregate_enricher(self) -> Callable[..., Any]:
        """Decorator form of `register_aggregate_enricher`.

        Example::

            @domain.aggregate_enricher
            def stamp_updated_at(aggregate):
                aggregate.updated_at = datetime.now(UTC)
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register_aggregate_enricher(fn)
            return fn

        return decorator

    #####################
    # Handling Commands #
    #####################
    def _enrich_command(
        self,
        command: BaseCommand,
        asynchronous: bool,
        idempotency_key: str | None = None,
        priority: int = 0,
        correlation_id: str | None = None,
    ) -> BaseCommand:
        return self._command_processor.enrich(
            command,
            asynchronous,
            idempotency_key=idempotency_key,
            priority=priority,
            correlation_id=correlation_id,
        )

    def process(
        self,
        command: Any,
        asynchronous: bool | None = None,
        idempotency_key: str | None = None,
        raise_on_duplicate: bool = False,
        priority: int | None = None,
        correlation_id: str | None = None,
        deadline: datetime | None = None,
        timeout: timedelta | None = None,
    ) -> Any | None:
        """Store a command in the event store and handle it now or later.

        The command is handled synchronously when ``asynchronous`` is ``False``
        or when the ``command_processing`` config is ``"sync"``. Otherwise the
        engine handles it later.

        Args:
            command: Instance of a ``@domain.command``-decorated class.
            asynchronous: Whether to handle the command later. Defaults to the
                ``command_processing`` config.
            idempotency_key: Key for deduplicating submissions. When the
                idempotency store already holds a success for this key, the
                cached result is returned and the command is not stored again.
            raise_on_duplicate: Raise ``DuplicateCommandError`` on a duplicate
                key. When ``False``, the cached result is returned.
            priority: Processing priority for the events this command produces.
                Defaults to the current ``processing_priority()`` context.
            correlation_id: Correlation ID carried by every command and event
                in the causal chain. A new one is generated when omitted.
            deadline: Absolute time after which the command must not run.
                Passed on to downstream commands in the same causal chain.
            timeout: Relative deadline, converted to ``now + timeout`` on
                submission.

        Returns:
            The command handler's return value when the command is handled
            synchronously. Otherwise, the command's position in the event
            store.

        Raises:
            IncorrectUsageError: If the command is not registered with the
                domain, or if both ``deadline`` and ``timeout`` are given.
            DuplicateCommandError: If ``raise_on_duplicate`` is ``True`` and the
                idempotency key was already processed.
            CommandExpiredError: If the deadline has passed when a synchronous
                handler is about to run.
        """
        return self._command_processor.process(
            command,
            asynchronous=asynchronous,
            idempotency_key=idempotency_key,
            raise_on_duplicate=raise_on_duplicate,
            priority=priority,
            correlation_id=correlation_id,
            deadline=deadline,
            timeout=timeout,
        )

    def command_handler_for(self, command: Any) -> type[BaseCommandHandler] | None:
        """Return Command Handler for a specific command."""
        return self._command_processor.handler_for(command)

    ###################
    # Handling Events #
    ###################
    def handlers_for(self, event: Any) -> set[Any]:
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
    def projectors_for(self, projection_cls: type[BaseProjection]) -> set[Any]:
        """Return Projectors listening to a specific projection

        Args:
            projection_cls (type[BaseProjection]): Projection to be consumed

        Returns:
            List[BaseProjector]: Projectors that have registered to consume the projection
        """
        return self.event_store.projectors_for(projection_cls)

    ############################
    # Repository Functionality #
    ############################

    def repository_for(self, element_cls: Any) -> BaseRepository:
        if isinstance(element_cls, str):
            raise IncorrectUsageError(
                f"Element {element_cls} is not registered in domain {self.name}",
                code=DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED,
                location="Domain.repository_for",
            )

        repository: BaseRepository
        if (
            element_cls.element_type == DomainObjects.AGGREGATE
            and element_cls.meta_.is_event_sourced
        ):
            # Return an Event Sourced repository. It is not a BaseRepository
            # subclass but is consumed repository-like (add/get/find_by) by
            # callers; cast to keep this method's public contract stable.
            repository = cast(
                BaseRepository, self.event_store.repository_for(element_cls)
            )
        else:
            # A cache-backed projection has no provider, so the lookup below
            # fails with `No provider configured with name 'None'`, which names
            # the wrong problem: the projection is not misconfigured, the caller
            # is at the wrong door. Say which door.
            if (
                getattr(element_cls, "element_type", None) == DomainObjects.PROJECTION
                and getattr(element_cls.meta_, "cache", None) is not None
            ):
                raise IncorrectUsageError(
                    f"`{element_cls.__name__}` is cache-backed "
                    f"(cache={element_cls.meta_.cache!r}), so it has no "
                    f"repository. Use `domain.cache_for({element_cls.__name__})` "
                    f"to write and `domain.view_for({element_cls.__name__})` to "
                    f"read. `repository_for()` is for provider-backed elements.",
                    code=DiagnosticCode.USAGE_CACHE_BACKED_NO_REPOSITORY,
                    location="Domain.repository_for",
                )

            # This is a regular aggregate or a projection
            repository = self.providers.repository_for(element_cls)
        return repository

    ###########################
    # ReadView Functionality #
    ###########################

    @overload
    def view_for(
        self, projection_cls: type[_ProjectionT]
    ) -> ReadView[_ProjectionT]: ...  # pragma: no cover
    # A checker without the Protean plugin sees a decorated projection as a
    # plain class, which the bound above rejects.
    @overload
    def view_for(self, projection_cls: type) -> ReadView[Any]: ...  # pragma: no cover
    def view_for(self, projection_cls: type) -> ReadView[Any]:
        """Return a read-only `ReadView` for querying a projection.

        The returned ``ReadView`` exposes ``get()``, ``query``
        (``ReadOnlyQuerySet``), ``find_by()``, ``count()``, and
        ``exists()``, but no mutation methods.

        Works with both database-backed and cache-backed projections.

        Args:
            projection_cls: A registered projection class.

        Returns:
            A ``ReadView`` bound to the projection's data store.

        Raises:
            IncorrectUsageError: If the element is not a projection.

        Example::

            view = domain.view_for(OrderSummary)
            order = view.get("order-123")
            results = view.query.filter(status="shipped").all()
        """
        if isinstance(projection_cls, str):
            raise IncorrectUsageError(
                f"Element {projection_cls} is not registered in domain {self.name}",
                code=DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED,
                location="Domain.view_for",
            )

        # ``element_type`` is a class var injected onto element classes at
        # registration; a plain ``type`` does not declare it.
        projection: Any = projection_cls
        if projection.element_type != DomainObjects.PROJECTION:
            raise IncorrectUsageError(
                f"`view_for` is only available for projections. "
                f"Received {projection.__name__} "
                f"({projection.element_type}).",
                code=DiagnosticCode.USAGE_NOT_A_PROJECTION,
                location="Domain.view_for",
            )

        return ReadView(self, projection_cls)

    # The overload stubs are typing-only: their ``...`` bodies never run, so
    # coverage reports them as partial branches. Exclude them the way codecov.yml
    # prescribes for genuinely unexecutable lines.
    @overload
    def dispatch(
        self, query: BaseQuery[_QueryResult]
    ) -> _QueryResult: ...  # pragma: no cover
    @overload
    def dispatch(self, query: Any) -> Any: ...  # pragma: no cover
    def dispatch(self, query: Any) -> Any:
        """Dispatch a query to its registered QueryHandler and return results.

        A query that declares its result type as ``BaseQuery[Result]`` resolves
        to ``Result`` at the call site. Anything else resolves to ``Any``: a
        bare ``BaseQuery`` subclass (which means ``BaseQuery[Any]``), and a
        decorator-only query such as ``@domain.query(...) class GetOrders:``,
        which a checker sees as a plain class because the decorator returns the
        class it was handed. All of them dispatch identically at runtime. A
        missing or unregistered handler raises ``IncorrectUsageError`` at
        runtime; it does not show up in the static return type.
        """
        return self._query_processor.dispatch(query)

    def _query_handler_for(self, query: Any) -> type | None:
        return self._query_processor.handler_for(query)

    #######################
    # Cache Functionality #
    #######################

    def cache_for(self, projection_cls: type[BaseProjection]) -> "BaseCache":
        return self.caches.cache_for(projection_cls)

    ################################
    # Raw Connection Functionality #
    ################################

    def connection_for(self, projection_cls: type) -> Any:
        """Return the raw database or cache connection for a projection.

        Use it to run queries specific to the backing store. For a
        database-backed projection it returns the provider's connection, such
        as a SQLAlchemy session, an Elasticsearch client, or a
        ``MemorySession``. For a cache-backed projection it returns the cache
        client, such as a ``redis.Redis`` instance or a plain ``dict``.

        Args:
            projection_cls: A registered projection class.

        Returns:
            The raw connection object for the projection's backing store.

        Raises:
            IncorrectUsageError: If the element is not a projection.

        Example::

            conn = domain.connection_for(OrderSummary)
            # Use conn to execute raw queries against the backing store
        """
        if isinstance(projection_cls, str):
            raise IncorrectUsageError(
                f"Element {projection_cls} is not registered in domain {self.name}",
                code=DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED,
                location="Domain.connection_for",
            )

        # ``element_type`` / ``meta_`` are injected onto element classes at
        # registration; they are not visible on the bare ``type`` annotation.
        projection: Any = projection_cls
        if projection.element_type != DomainObjects.PROJECTION:
            raise IncorrectUsageError(
                f"`connection_for` is only available for projections. "
                f"Received {projection.__name__} "
                f"({projection.element_type}).",
                code=DiagnosticCode.USAGE_NOT_A_PROJECTION,
                location="Domain.connection_for",
            )

        if projection.meta_.cache:
            return self.caches.get_connection(projection.meta_.cache)
        else:
            return self.providers.get_connection(projection.meta_.provider)

    ##########################
    # Snapshot Functionality #
    ##########################

    def _require_event_store(self) -> "BaseEventStore":
        """Return the initialized event store, or raise a clear error.

        The wrapper's ``store`` is ``None`` until ``domain.init()`` runs; these
        event-store operations are only valid afterwards.
        """
        store = self.event_store.store
        if store is None:
            raise ConfigurationError(
                "Event store is not initialized. Call `domain.init()` first.",
                code=DiagnosticCode.CONFIG_EVENT_STORE_NOT_INITIALIZED,
                location="Domain._require_event_store",
            )
        return store

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
                f"`{aggregate_cls.__name__}` is not registered in domain {self.name}",
                code=DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED,
                location="Domain.create_snapshot",
            )

        created: bool = self._require_event_store().create_snapshot(
            aggregate_cls, identifier
        )
        return created

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
                f"`{aggregate_cls.__name__}` is not registered in domain {self.name}",
                code=DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED,
                location="Domain.create_snapshots",
            )

        count: int = self._require_event_store().create_snapshots(aggregate_cls)
        return count

    def create_all_snapshots(self) -> dict[str, int]:
        """Create snapshots for all event-sourced aggregates in the domain.

        Must be called after ``domain.init()`` and within ``domain.domain_context()``.

        Returns:
            Dictionary mapping aggregate class names to the number of
            snapshots created.
        """
        results: dict[str, int] = {}
        for record in self.registry._elements[DomainObjects.AGGREGATE.value].values():
            if record.cls.meta_.is_event_sourced and not record.internal:
                count = self._require_event_store().create_snapshots(record.cls)
                results[record.cls.__name__] = count

        return results

    ##############################
    # Correlation Trace          #
    ##############################

    def correlation_trace(self, correlation_id: str) -> list["CausationNode"]:
        """Return the messages in a correlation chain, in causal order.

        The list is in depth-first order: each message appears before the
        messages it caused.

        Must be called after ``domain.init()`` and within
        ``domain.domain_context()``.

        Args:
            correlation_id: The correlation ID to trace.

        Returns:
            Ordered list of [`CausationNode`][protean.port.event_store.CausationNode]
            objects.  Empty list if no messages are found.

        Example::

            chain = domain.correlation_trace(correlation_id)
            for node in chain:
                print(f"{node.kind}: {node.message_type}")
        """
        root = self._require_event_store().build_causation_tree(correlation_id)
        if root is None:
            return []

        # Flatten tree via depth-first pre-order traversal
        result: list[CausationNode] = []

        def _walk(node: CausationNode) -> None:
            result.append(node)
            for child in node.children:
                _walk(child)

        _walk(root)
        return result

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
        return rebuild_all_projections(self, batch_size)

    def make_shell_context(self) -> dict[str, Any]:
        """Return a dictionary of context variables for a shell session."""
        values: dict[str, Any] = {"domain": self}

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

    def _initialize_outbox(self) -> None:
        self._infrastructure.initialize_outbox()

    def _get_outbox_repo(self, provider_name: str) -> "OutboxRepository":
        # The infrastructure builds an OutboxRepository (typed BaseRepository at
        # its boundary); narrow so callers see count_by_status et al.
        return cast(
            "OutboxRepository", self._infrastructure.get_outbox_repo(provider_name)
        )

    def _initialize_processed_messages(self) -> None:
        self._infrastructure.initialize_processed_messages()

    def _get_processed_message_repo(self, provider_name: str) -> BaseRepository:
        return self._infrastructure.get_processed_message_repo(provider_name)

    # ------------------------------------------------------------------
    # Public database lifecycle API
    # ------------------------------------------------------------------

    def setup_database(self) -> None:
        """Create all database tables (aggregates, entities, projections, outbox)."""
        self._infrastructure.setup_database()

    def setup_outbox(self) -> None:
        """Create only outbox tables."""
        self._infrastructure.setup_outbox()

    def truncate_database(self) -> None:
        """Delete all rows from every table without dropping the tables."""
        self._infrastructure.truncate_database()

    def drop_database(self) -> None:
        """Drop all database tables."""
        self._infrastructure.drop_database()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def configure_logging(self, **kwargs: Any) -> None:
        """Set up structured logging that adds correlation context to every record.

        Calls `protean.utils.logging.configure_logging`. Every log record, from
        the standard library or structlog, then carries ``correlation_id`` and
        ``causation_id`` from the active domain context.

        Each setting comes from the first of these that sets it:

        1. Keyword arguments to this method.
        2. The ``PROTEAN_LOG_LEVEL`` environment variable, for the level only.
        3. The ``[logging]`` section of ``domain.toml``.
        4. Defaults based on the environment.

        ``[logging.per_logger]`` sets the level of individual loggers.

        Args:
            **kwargs: Forwarded to `protean.utils.logging.configure_logging`
                (``level``, ``format``, ``log_dir``, etc.). Explicit values
                override anything in ``domain.toml``.

        Example::

            domain.configure_logging()           # sensible defaults
            domain.configure_logging(level="DEBUG", format="json")
        """
        # --- Merge domain.toml [logging] with explicit kwargs ---
        logging_config = self.config.get("logging", {})
        telemetry_enabled = bool(self.config.get("telemetry", {}).get("enabled"))
        config_kwargs: dict[str, Any] = {}

        # level: env var overrides config, but explicit kwargs override both.
        # Only forward config level when the env var is absent.
        cfg_level = logging_config.get("level", "")
        if cfg_level and "PROTEAN_LOG_LEVEL" not in os.environ:
            config_kwargs["level"] = cfg_level

        # Other string keys: empty string means "use default"
        for key in ("format", "log_dir", "log_file_prefix"):
            val = logging_config.get(key, "")
            if val:
                config_kwargs[key] = val

        # Numeric keys: forward when present (default_config always provides them)
        for key in ("max_bytes", "backup_count"):
            val = logging_config.get(key)
            if val is not None:
                config_kwargs[key] = int(val)

        # Dict key: forward when non-empty
        per_logger = logging_config.get("per_logger")
        if per_logger:
            config_kwargs["per_logger"] = per_logger

        # List of sensitive keys to redact
        redact = logging_config.get("redact")
        if redact:
            config_kwargs["redact"] = list(redact)

        # Explicit kwargs override config values
        config_kwargs.update(kwargs)

        # Build processor list without mutating any caller-supplied sequence.
        # Built-in context injectors (correlation, OTel) run before any
        # caller-supplied processors so user code observing the event dict
        # (e.g. redaction, routing, enrichment) sees the injected fields.
        # Skip OTel injection when telemetry is disabled so the structlog
        # chain does not pay the cost of a no-op processor on every log call.
        extra_processors = config_kwargs.pop("extra_processors", None)
        extra: list[Any] = [protean_correlation_processor]
        if telemetry_enabled:
            extra.append(protean_otel_processor)
        extra.extend(list(extra_processors or []))

        # Tail sampling for wide events — opt-in via [logging.sampling].enabled.
        # Sampling runs against the un-redacted event dict so `status` and
        # `message_type` are still readable; redaction (appended later inside
        # configure_logging) masks what survives.
        sampling_config = logging_config.get("sampling", {}) or {}
        sampling_enabled = bool(sampling_config.get("enabled", False))
        sampling_kwargs: dict[str, Any] = {}
        if sampling_enabled:
            sampling_kwargs = {
                "default_rate": sampling_config.get("default_rate", 0.05),
                "always_keep_errors": sampling_config.get("always_keep_errors", True),
                "always_keep_slow": sampling_config.get("always_keep_slow", True),
                "critical_streams": sampling_config.get("critical_streams", []),
            }
            extra.append(TailSamplingProcessor(**sampling_kwargs))

        configure_logging(extra_processors=extra, **config_kwargs)

        # Attach the correlation filter to the root logger and to each root
        # handler. A logger's filters do not run for records that propagate
        # from child loggers, so the handler filters cover those records.
        # Repeated calls add no duplicates.
        _install_root_filter(ProteanCorrelationFilter())
        if telemetry_enabled:
            _install_root_filter(OTelTraceContextFilter())
        # These installs append after any redaction filter already there,
        # and the context filters write the ids redaction may need to
        # mask, so move redaction back after them on the root logger and on
        # each root handler.
        _move_redaction_filter_last()

        # Tail sampling filter on the protean.access stdlib logger — covers
        # the primary wide event emission path (access_logger is a stdlib
        # logger so events never reach the structlog processor chain).
        if sampling_enabled and not any(
            isinstance(f, TailSamplingFilter) for f in access_logger.filters
        ):
            access_logger.addFilter(TailSamplingFilter(**sampling_kwargs))
