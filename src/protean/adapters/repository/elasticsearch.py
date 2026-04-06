"""Module containing repository implementation for Elasticsearch"""

import json
import logging
from typing import Any
from uuid import UUID

import elasticsearch_dsl
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConflictError, NotFoundError
from elasticsearch_dsl import (
    Boolean as ESBoolean,
    Date as ESDate,
    Document,
    Float as ESFloat,
    Index,
    Integer as ESInteger,
    Keyword,
    Mapping,
    Nested as ESNested,
    Search,
    query,
)

from protean.core.database_model import BaseDatabaseModel
from protean.core.queryset import ResultSet
from protean.exceptions import (
    DatabaseError,
    ExpectedVersionError,
    NotSupportedError,
    ObjectNotFoundError,
)
from protean.port.dao import BaseDAO, BaseLookup
from protean.port.provider import BaseProvider, DatabaseCapabilities
from protean.utils import IdentityStrategy, IdentityType, fully_qualified_name
from protean.utils.container import Options
from protean.utils.globals import current_domain, current_uow
from protean.utils.query import Q
from protean.utils.reflection import attributes, id_field
from protean.fields.association import _ReferenceField
from protean.fields.basic import ValueObjectList
from protean.fields.embedded import _ShadowField
from protean.fields.resolved import ResolvedField

logger = logging.getLogger(__name__)

# Python type → elasticsearch_dsl field type mapping for auto-generated models.
# These are sensible defaults; users override via custom @domain.model classes
# for ES-specific tuning (analyzers, multi-fields, etc.).
_PYTHON_TYPE_TO_ES = {
    str: Keyword,
    int: ESInteger,
    float: ESFloat,
    bool: ESBoolean,
}


def _resolve_python_type(field_obj: ResolvedField):
    """Unwrap Optional/Union and generic aliases to get the base Python type."""
    import types
    import typing

    python_type = field_obj._python_type
    origin = typing.get_origin(python_type)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(python_type) if a is not type(None)]
        if args:
            python_type = args[0]
            # Re-check origin for the unwrapped type (e.g. list[Any])
            origin = typing.get_origin(python_type)

    # Resolve generic aliases like list[Any] → list, dict[str, Any] → dict
    if origin is not None:
        python_type = origin

    return python_type


def _es_field_mapping_for(field_obj) -> elasticsearch_dsl.Field | None:
    """Map a Protean field to an elasticsearch_dsl field type.

    Returns a sensible default ES field, or None for fields that should use
    Elasticsearch's dynamic mapping (List, Dict). For ES-specific tuning
    (analyzers, multi-fields, etc.), users should define a custom @domain.model.
    """
    from datetime import date as _date
    from datetime import datetime as _datetime

    # ShadowField (flattened ValueObject attribute): delegate to inner field
    if isinstance(field_obj, _ShadowField):
        return _es_field_mapping_for(field_obj.field_obj)

    # ResolvedField (Pydantic shim)
    if isinstance(field_obj, ResolvedField):
        if field_obj.identifier:
            return Keyword()
        if field_obj.increment:
            return ESInteger()

        python_type = _resolve_python_type(field_obj)

        # Date/datetime
        if python_type in (_datetime, _date):
            return ESDate()

        # Dict / List → skip explicit mapping, let ES use dynamic mapping.
        # ESObject(enabled=False) breaks serialization of plain values.
        if python_type in (dict, list):
            return None

        return _PYTHON_TYPE_TO_ES.get(python_type, Keyword)()

    # Reference field (FK shadow): always Keyword
    if isinstance(field_obj, _ReferenceField):
        return Keyword()

    # ValueObjectList: nested objects
    if isinstance(field_obj, ValueObjectList):
        return ESNested()

    # Fallback
    return Keyword()


operators = {
    "exact": "__eq__",
    "iexact": "ilike",
    "contains": "contains",
    "icontains": "ilike",
    "startswith": "startswith",
    "endswith": "endswith",
    "gt": "__gt__",
    "gte": "__ge__",
    "lt": "__lt__",
    "lte": "__le__",
    "in": "in_",
    "overlap": "overlap",
    "any": "any",
}


class ElasticsearchModel(Document, BaseDatabaseModel):
    """A database model for the Elasticsearch index"""

    @classmethod
    def from_entity(cls, entity) -> "ElasticsearchModel":
        """Convert the entity to a Elasticsearch record"""
        item_dict = cls._entity_to_dict(entity)

        # Remap _version → entity_version to avoid conflict with ES _version metadata
        if "_version" in item_dict:
            item_dict["entity_version"] = item_dict.pop("_version")

        model_obj = cls(**item_dict)

        # Elasticsearch stores identity in a special field `meta.id`.
        # Set `meta.id` to the identifier set in entity
        id_field_obj = id_field(cls.meta_.part_of)
        assert id_field_obj is not None
        id_field_name = id_field_obj.field_name

        if id_field_name in item_dict:
            assert model_obj.meta is not None
            model_obj.meta.id = item_dict[id_field_name]

        return model_obj

    @classmethod
    def to_entity(cls, item: "ElasticsearchModel"):
        """Convert the elasticsearch document to an entity"""
        item_dict = {}

        # Convert the values in ES Model as a dictionary
        values = item.to_dict()
        for field_name in attributes(cls.meta_.part_of):
            item_dict[field_name] = values.get(field_name, None)

        assert item.meta is not None
        identifier = None
        if (
            current_domain.config["identity_strategy"] == IdentityStrategy.UUID.value
            and current_domain.config["identity_type"] == IdentityType.UUID.value
            and isinstance(item.meta.id, str)
        ):
            identifier = UUID(item.meta.id)
        else:
            identifier = item.meta.id

        # Elasticsearch stores identity in a special field `meta.id`.
        # Extract identity from `meta.id` and set identifier
        id_field_obj = id_field(cls.meta_.part_of)
        assert id_field_obj is not None
        id_field_name = id_field_obj.field_name
        item_dict[id_field_name] = identifier

        # Set version from document fields, only if `_version` attr is present
        # We store the entity version as a regular field rather than using ES native versioning
        # Use 'entity_version' to avoid conflict with Elasticsearch's _version metadata
        if hasattr(cls.meta_.part_of, "_version"):
            version_value = values.get("entity_version", -1)
            item_dict["_version"] = version_value

        entity_obj = cls.meta_.part_of(item_dict)

        return entity_obj


class ESSession:
    """A Session wrapper for Elasticsearch Database.

    Elasticsearch does not support Transactions or Sessions, so this class is
    essential a no-op, and acts as a passthrough for all transactions.
    """

    def __init__(self, provider, new_connection=False):
        self._provider = provider
        self.is_active = True

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class ElasticsearchDAO(BaseDAO):
    def __repr__(self) -> str:
        return f"ElasticsearchDAO <{self.entity_cls.__name__}>"

    def _build_filters(self, criteria: Q):
        """Recursively Build the filters from the criteria object"""
        composed_query = query.Q()

        if criteria.connector == criteria.AND:
            for child in criteria.children:
                if isinstance(child, Q):
                    composed_query = composed_query & self._build_filters(child)
                else:
                    stripped_key, lookup_class = self.provider._extract_lookup(child[0])
                    lookup = lookup_class(
                        stripped_key,
                        child[1],
                        database_model_cls=self.database_model_cls,
                    )
                    expression = lookup.as_expression()
                    if criteria.negated:
                        assert expression is not None
                        composed_query = composed_query & ~expression
                    else:
                        composed_query = composed_query & expression
        else:
            for child in criteria.children:
                if isinstance(child, Q):
                    composed_query = composed_query | self._build_filters(child)
                else:
                    stripped_key, lookup_class = self.provider._extract_lookup(child[0])
                    lookup = lookup_class(
                        stripped_key,
                        child[1],
                        database_model_cls=self.database_model_cls,
                    )
                    expression = lookup.as_expression()
                    if criteria.negated:
                        assert expression is not None
                        composed_query = composed_query | ~expression
                    else:
                        composed_query = composed_query | expression

        return composed_query

    def _filter(
        self, criteria: Q, offset: int = 0, limit: int = 10, order_by: list = ()
    ) -> ResultSet:
        """
        Filter objects from the data store. Method must return a `ResultSet`
        object
        """
        conn = self.provider.get_connection()

        # Build the filters from the criteria
        q = elasticsearch_dsl.Q()
        if criteria.children:
            q = self._build_filters(criteria)

        s = (
            Search(using=conn, index=self.database_model_cls._index._name)
            .query(q)
            .params(version=True)
        )

        if order_by:
            s = s.sort(*order_by)

        if limit is not None:
            s = s[offset : offset + limit]
        else:
            # When limit is None, we want to return all results
            # Elasticsearch has a default limit of 10 and max of 10000 by default
            # We set a very large limit to effectively get all results
            s = s[offset : offset + 10000]

        # Return the results
        try:
            response = s.execute()

            # Convert hits to ElasticsearchModel objects with proper metadata
            model_items = []
            for hit in response.hits:
                # Create a model object from the hit data
                model_obj = self.database_model_cls(**hit.to_dict())  # type: ignore[reportCallIssue]
                model_obj.meta.id = hit.meta.id
                if hasattr(hit.meta, "version"):
                    model_obj.meta.version = hit.meta.version
                model_items.append(model_obj)

            result = ResultSet(
                offset=offset,
                limit=limit,
                total=response.hits.total.value,
                items=model_items,
            )
        except Exception as exc:
            # Check if it's a sort field mapping error
            if "No mapping found for" in str(exc) and "in order to sort on" in str(exc):
                logger.warning(
                    f"Sort field not found in mapping, retrying without sort: {exc}"
                )
                # Retry without sorting
                try:
                    s_no_sort = (
                        Search(using=conn, index=self.database_model_cls._index._name)
                        .query(q)
                        .params(version=True)
                    )

                    if limit is not None:
                        s_no_sort = s_no_sort[offset : offset + limit]
                    else:
                        s_no_sort = s_no_sort[offset : offset + 10000]

                    response = s_no_sort.execute()

                    # Convert hits to ElasticsearchModel objects with proper metadata
                    model_items = []
                    for hit in response.hits:
                        model_obj = self.database_model_cls(**hit.to_dict())  # type: ignore[reportCallIssue]
                        model_obj.meta.id = hit.meta.id
                        if hasattr(hit.meta, "version"):
                            model_obj.meta.version = hit.meta.version
                        model_items.append(model_obj)

                    result = ResultSet(
                        offset=offset,
                        limit=limit,
                        total=response.hits.total.value,
                        items=model_items,
                    )
                except Exception as retry_exc:
                    logger.error(f"Error while filtering (retry): {retry_exc}")
                    raise DatabaseError(
                        f"Database error during filtering: {str(retry_exc)}",
                        original_exception=retry_exc,
                    )
            else:
                logger.error(f"Error while filtering: {exc}")
                raise DatabaseError(
                    f"Database error during filtering: {str(exc)}",
                    original_exception=exc,
                )

        return result

    def _create(self, model_obj: Any):
        """Create a new database model object from the entity"""
        conn = self.provider.get_connection()

        try:
            model_obj.save(
                refresh=True,
                index=self.database_model_cls._index._name,
                using=conn,
            )
        except Exception as exc:
            logger.error(f"Error while creating: {exc}")
            raise DatabaseError(
                f"Database error during creation: {str(exc)}", original_exception=exc
            )

        return model_obj

    def _update(self, model_obj: Any, expected_version: int | None = None):
        """Update a database model object in the data store and return it.

        When ``expected_version`` is set, uses ES native ``if_seq_no`` /
        ``if_primary_term`` for atomic optimistic concurrency control.
        """
        conn = self.provider.get_connection()

        identifier = model_obj.meta.id

        # Fetch the record to verify existence and capture seq_no/primary_term
        try:
            existing = self.database_model_cls.get(
                id=identifier, using=conn, index=self.database_model_cls._index._name
            )
        except NotFoundError as exc:
            logger.error(f"Database Record not found: {exc}")
            raise ObjectNotFoundError(
                f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        if expected_version is not None:
            # Fast-fail with a clear error message including version numbers.
            # The ES native if_seq_no/if_primary_term guard below is the true
            # atomic check, but its 409 response lacks version details.
            stored_version = getattr(existing, "_version", None)
            if stored_version != expected_version:
                raise ExpectedVersionError(
                    f"Wrong expected version: {expected_version} "
                    f"(Aggregate: {self.entity_cls.__name__}({identifier}), "
                    f"Version: {stored_version})"
                )

        try:
            save_kwargs: dict[str, Any] = {
                "refresh": True,
                "index": self.database_model_cls._index._name,
                "using": conn,
            }
            # Use ES native OCC: if another write sneaked in between our
            # GET and this SAVE, ES will reject it with a 409 Conflict.
            if expected_version is not None:
                save_kwargs["if_seq_no"] = existing.meta.seq_no
                save_kwargs["if_primary_term"] = existing.meta.primary_term

            model_obj.save(**save_kwargs)
        except ConflictError as exc:
            # ES rejected the write because seq_no/primary_term changed
            raise ExpectedVersionError(
                f"Wrong expected version: {expected_version} "
                f"(Aggregate: {self.entity_cls.__name__}({identifier}))"
            ) from exc
        except Exception as exc:
            logger.error(f"Error while updating: {exc}")
            raise DatabaseError(
                f"Database error during update: {str(exc)}", original_exception=exc
            )

        return model_obj

    def _update_all(self, criteria: Q, *args, **kwargs):
        """Updates object directly in the data store and returns update count"""
        conn = self.provider.get_connection()

        # Build the filters from the criteria
        q = elasticsearch_dsl.Q()
        if criteria and criteria.children:
            q = self._build_filters(criteria)

        # Prepare update values
        values = {}
        if args:
            values = args[0]  # `args[0]` is required because `*args` is sent as a tuple
        values.update(kwargs)

        if not values:
            return 0

        # Build the update script
        script_lines = []
        params = {}
        for field_name, field_value in values.items():
            param_name = f"new_{field_name}"
            script_lines.append(f"ctx._source.{field_name} = params.{param_name}")
            params[param_name] = field_value

        script = "; ".join(script_lines)

        try:
            # Use update_by_query API
            response = conn.update_by_query(
                index=self.database_model_cls._index._name,
                body={
                    "query": q.to_dict() if q else {"match_all": {}},
                    "script": {"source": script, "params": params},
                },
                refresh=True,
            )

            return response.get("updated", 0)
        except Exception as exc:
            logger.error(f"Error while updating all: {exc}")
            raise DatabaseError(
                f"Database error during update_all: {str(exc)}", original_exception=exc
            )

    def _delete(self, model_obj):
        """Delete a Record from the Repository"""
        conn = self.provider.get_connection()

        try:
            model_obj.delete(
                index=self.database_model_cls._index._name,
                using=conn,
                refresh=True,
            )
        except NotFoundError as exc:
            logger.error(f"Database Record not found: {exc}")
            id_field_obj = id_field(self.entity_cls)
            assert id_field_obj is not None
            identifier = getattr(model_obj, id_field_obj.attribute_name)
            raise ObjectNotFoundError(
                f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                f"does not exist."
            )
        except Exception as exc:
            logger.error(f"Error while deleting: {exc}")
            raise DatabaseError(
                f"Database error during deletion: {str(exc)}", original_exception=exc
            )

        return model_obj

    def _delete_all(self, criteria: Q = None):
        """Delete all records matching criteria from the Repository"""
        conn = self.provider.get_connection()

        # Build the filters from the criteria
        q = elasticsearch_dsl.Q()
        if criteria and criteria.children:
            q = self._build_filters(criteria)

        s = Search(using=conn, index=self.database_model_cls._index._name).query(q)

        # Return the results
        try:
            response = s.delete()

            # `Search.delete` does not refresh index, so we have to manually refresh
            index = Index(name=self.entity_cls.meta_.schema_name, using=conn)
            index.refresh()
        except Exception as exc:
            logger.error(f"Error while deleting records: {exc}")
            raise DatabaseError(
                f"Database error during delete_all: {str(exc)}", original_exception=exc
            )

        return response.deleted

    def _raw(self, query: Any, data: Any = None):
        """Not supported — Elasticsearch does not support raw queries.

        This method is never reached because ``QuerySet.raw()`` gates access
        via provider capability checks. It exists only to satisfy the abstract
        method contract.
        """
        raise NotSupportedError(
            f"Provider '{self.provider.name}' ({self.provider.__class__.__name__}) "
            "does not support raw queries"
        )

    def has_table(self) -> bool:
        """Check if the index exists in Elasticsearch.

        Returns True if the index exists, False otherwise.
        """
        conn = self.provider.get_connection()
        return conn.indices.exists(index=self.database_model_cls._index._name)


class ESProvider(BaseProvider):
    __database__ = "elasticsearch"

    @property
    def capabilities(self) -> DatabaseCapabilities:
        """Elasticsearch supports document storage with schema management but no transactions."""
        return DatabaseCapabilities.DOCUMENT_STORE

    def __init__(self, name, domain, conn_info: dict):
        """Initialize Provider with Connection/Adapter details"""

        # Use database_uri as is if it's a json, otherwise convert it to json
        if isinstance(conn_info["database_uri"], str):
            conn_info["database_uri"] = json.loads(conn_info["database_uri"])
        else:
            conn_info["database_uri"] = conn_info["database_uri"]

        super().__init__(name, domain, conn_info)

        # A temporary cache of already constructed model classes
        self._database_model_classes = {}

        # Create a persistent Elasticsearch client
        self._client = Elasticsearch(
            self.conn_info["database_uri"]["hosts"],
            use_ssl=self.conn_info.get("USE_SSL", False),
            verify_certs=self.conn_info.get("VERIFY_CERTS", False),
        )

    def namespaced_schema_name(self, schema_name):
        # Prepend Namespace prefix if one has been provided
        if "NAMESPACE_PREFIX" in self.conn_info and self.conn_info["NAMESPACE_PREFIX"]:
            # Use custom separator if provided
            separator = "_"
            if (
                "NAMESPACE_SEPARATOR" in self.conn_info
                and self.conn_info["NAMESPACE_SEPARATOR"]
            ):
                separator = self.conn_info["NAMESPACE_SEPARATOR"]

            schema_name = (
                f"{self.conn_info['NAMESPACE_PREFIX']}{separator}{schema_name}"
            )

        return schema_name

    def _compute_keyword_fields(
        self, entity_cls, database_model_cls=None, custom_attrs=None
    ):
        """Precompute which fields need a .keyword subfield for exact matching.

        With explicit mappings, only fields mapped as ``Text`` (from custom
        @domain.model classes) need the ``.keyword`` suffix.  Auto-generated
        models map strings to ``Keyword``, which supports exact matching
        natively without a subfield.

        Returns a set of field names that should use the .keyword subfield.
        """
        from elasticsearch_dsl import Text as ESText

        keyword_fields: set[str] = set()

        # When a custom model provides explicit ES field definitions,
        # detect which are Text-type (those need .keyword for exact match)
        if custom_attrs:
            for attr_name, attr_value in custom_attrs.items():
                if isinstance(attr_value, ESText):
                    keyword_fields.add(attr_name)

        return keyword_fields

    def get_session(self):
        """Establish a new session with the database.

        Typically the session factory should be created once per application. Which is then
        held on to and passed to different transactions.

        In Protean's case, the session scope and the transaction scope match. Which means that a
        new session is created when a transaction needs to be initiated (at the beginning of
        request handling, for example) and terminated (after committing or rolling back) at the end
        of the process. The session will be used as a component in Unit of Work Pattern, to handle
        transactions reliably.

        Sessions are made available to requests as part of a Context Manager.
        """
        return ESSession(self)

    def get_connection(self):
        """Get the connection object for the repository"""
        return self._client

    def is_alive(self) -> bool:
        """Check if the connection is alive"""
        return self._client.ping()

    def get_dao(self, entity_cls, database_model_cls):
        """Return a DAO object configured with a live connection"""
        return ElasticsearchDAO(self.domain, self, entity_cls, database_model_cls)

    def decorate_database_model_class(self, entity_cls, database_model_cls):
        schema_name = self.namespaced_schema_name(
            database_model_cls.derive_schema_name()
        )
        cache_key = fully_qualified_name(entity_cls)

        # Return the model class if it was already seen/decorated
        if cache_key in self._database_model_classes:
            return self._database_model_classes[cache_key]

        # If `database_model_cls` is already subclassed from ElasticsearchModel,
        #   this method call is a no-op
        if issubclass(database_model_cls, ElasticsearchModel):
            return database_model_cls
        else:
            custom_attrs = {
                key: value
                for (key, value) in vars(database_model_cls).items()
                if key not in ["Meta", "__module__", "__doc__", "__weakref__"]
            }

            # Construct Inner Index class with options
            options = {}

            # Set schema name intelligently
            #   database_model_cls.meta_.schema_name - would come from custom model's options
            #   database_model_cls._index._name - would come from custom model's `Index` inner class
            #   schema_name - is derived
            index_name = (
                database_model_cls._index._name
                if hasattr(database_model_cls, "_index")
                else None
            )
            options["name"] = (
                database_model_cls.meta_.schema_name or index_name or schema_name
            )

            # Gather adapter settings
            if "SETTINGS" in self.conn_info and self.conn_info["SETTINGS"]:
                options["settings"] = self.conn_info["SETTINGS"]

            # Set options into `Index` inner class for ElasticsearchModel
            index_cls = type("Index", (object,), options)

            # Add the Index class to the custom attributes
            custom_attrs.update({"Index": index_cls})

            # Snapshot custom attrs before type() — the ES DSL Document
            # metaclass mutates the dict, removing field entries.
            custom_attrs_snapshot = dict(custom_attrs)

            decorated_database_database_model_cls = type(
                database_model_cls.__name__,
                (ElasticsearchModel, database_model_cls),
                custom_attrs,
            )

            # Auto-map entity attributes not explicitly defined in the custom model.
            # User-defined ES fields take precedence.
            m = Mapping()
            entity_attributes = attributes(entity_cls)
            for attr_name, field_obj in entity_attributes.items():
                # Skip _version — remapped to entity_version in from_entity()
                if attr_name == "_version":
                    continue
                if attr_name not in custom_attrs_snapshot:
                    es_field = _es_field_mapping_for(field_obj)
                    if es_field is not None:
                        m.field(attr_name, es_field)

            if hasattr(entity_cls, "_version"):
                if "entity_version" not in custom_attrs_snapshot:
                    m.field("entity_version", ESInteger())

            decorated_database_database_model_cls._index.mapping(m)

            # Precompute and cache field type information for efficient lookup operations
            keyword_fields = self._compute_keyword_fields(
                entity_cls, custom_attrs=custom_attrs_snapshot
            )
            decorated_database_database_model_cls._keyword_fields = keyword_fields

            # Memoize the constructed model class
            self._database_model_classes[cache_key] = (
                decorated_database_database_model_cls
            )

            return decorated_database_database_model_cls

    def construct_database_model_class(self, entity_cls):
        """Return a fully-baked Model class for a given Entity class"""
        database_model_cls = None
        cache_key = fully_qualified_name(entity_cls)
        schema_name = self.namespaced_schema_name(entity_cls.meta_.schema_name)

        # Return the model class if it was already seen/decorated
        if cache_key in self._database_model_classes:
            database_model_cls = self._database_model_classes[cache_key]
        else:
            meta_ = Options()
            meta_.part_of = entity_cls

            # Construct Inner Index class with options
            options = {}
            options["name"] = schema_name
            if "SETTINGS" in self.conn_info and self.conn_info["SETTINGS"]:
                options["settings"] = self.conn_info["SETTINGS"]

            index_cls = type("Index", (object,), options)

            attrs = {"meta_": meta_, "Index": index_cls}

            database_model_cls = type(
                entity_cls.__name__ + "Model", (ElasticsearchModel,), attrs
            )

            # Build explicit mapping from entity attributes
            m = Mapping()
            entity_attributes = attributes(entity_cls)
            for attr_name, field_obj in entity_attributes.items():
                # Skip _version — it's remapped to entity_version in from_entity()
                # to avoid conflict with ES's internal _version metadata
                if attr_name == "_version":
                    continue
                es_field = _es_field_mapping_for(field_obj)
                if es_field is not None:
                    m.field(attr_name, es_field)

            # Map entity_version if the entity supports versioning
            # (_version is stored as entity_version in ES)
            if hasattr(entity_cls, "_version"):
                m.field("entity_version", ESInteger())

            database_model_cls._index.mapping(m)

            # Precompute and cache field type information for efficient lookup operations
            keyword_fields = self._compute_keyword_fields(entity_cls)
            database_model_cls._keyword_fields = keyword_fields

            # Memoize the constructed model class
            self._database_model_classes[cache_key] = database_model_cls

        # Set Entity Class as a class level attribute for the Model, to be able to reference later.
        return database_model_cls

    def _raw(self, query: Any, data: Any = None):
        """Not supported — Elasticsearch does not support raw queries.

        This method is never reached because the base class ``raw()`` gates
        access via capability checks. It exists only to satisfy the abstract
        method contract.
        """
        raise NotSupportedError(
            f"Provider '{self.name}' ({self.__class__.__name__}) "
            "does not support raw queries"
        )

    def _data_reset(self):
        """Reset data"""
        conn = self.get_connection()

        # Get all elements that have been registered with the domain
        elements = {
            **self.domain.registry.aggregates,
            **self.domain.registry.entities,
            **self.domain.registry.projections,
        }

        for _, element_record in elements.items():
            cls = element_record.cls
            # Skip event-sourced aggregates — they have no database model
            if getattr(cls.meta_, "is_event_sourced", False):
                continue
            part_of = getattr(cls.meta_, "part_of", None)
            if part_of and getattr(part_of.meta_, "is_event_sourced", False):
                continue

            provider = current_domain.providers[cls.meta_.provider]
            if provider != self:
                continue

            repo = self.domain.repository_for(cls)
            database_model_cls = repo._database_model
            if conn.indices.exists(index=database_model_cls._index._name):
                # Delete all documents from the index using delete_by_query with match_all
                # This clears the data but keeps the index structure
                conn.delete_by_query(
                    refresh=True,
                    index=database_model_cls._index._name,
                    body={"query": {"match_all": {}}},
                )

        # Discard any active Unit of Work
        if current_uow and current_uow.in_progress:
            current_uow.rollback()

    def close(self):
        """Close the provider and clean up resources.

        Closes the Elasticsearch client and its underlying connection pool
        to free up network resources and prevent connection leaks.
        """
        if hasattr(self, "_client") and self._client:
            self._client.close()

    def _create_database_artifacts(self):
        conn = self.get_connection()

        # Loop through self.domain.registry._elements and extract the classes under
        #   the keys 'AGGREGATE', 'ENTITY', and 'PROJECTION'
        #   We don't use properties because we want to access even the internal elements
        elements = {}

        for element_type in ["AGGREGATE", "ENTITY", "PROJECTION"]:
            if element_type in self.domain.registry._elements:
                elements.update(self.domain.registry._elements[element_type])

        for _, element_record in elements.items():
            cls = element_record.cls
            # Skip event-sourced aggregates — they use the event store, not ES indices
            if getattr(cls.meta_, "is_event_sourced", False):
                continue
            # Skip entities that belong to event-sourced aggregates
            part_of = getattr(cls.meta_, "part_of", None)
            if part_of and getattr(part_of.meta_, "is_event_sourced", False):
                continue

            provider = current_domain.providers[cls.meta_.provider]
            if provider != self:
                continue

            database_model_cls = current_domain.repository_for(cls)._database_model
            if not database_model_cls._index.exists(using=conn):
                # We use database_model_cls here to ensure the index is created along with mappings
                database_model_cls.init(using=conn)

    def _drop_database_artifacts(self):
        conn = self.get_connection()

        elements = {
            **self.domain.registry.aggregates,
            **self.domain.registry.entities,
            **self.domain.registry.projections,
        }
        for _, element_record in elements.items():
            cls = element_record.cls
            # Skip event-sourced aggregates — they have no database model
            if getattr(cls.meta_, "is_event_sourced", False):
                continue
            part_of = getattr(cls.meta_, "part_of", None)
            if part_of and getattr(part_of.meta_, "is_event_sourced", False):
                continue

            provider = self.domain.providers[cls.meta_.provider]
            if provider != self:
                continue

            database_model_cls = self.domain.repository_for(cls)._database_model
            if database_model_cls._index.exists(using=conn):
                conn.indices.delete(index=database_model_cls._index._name)


class DefaultLookup(BaseLookup):
    """Base class with default implementation of expression construction"""

    def process_target(self):
        """Return target with transformations, if any"""
        if isinstance(self.target, UUID):
            self.target = str(self.target)

        return self.target

    def should_use_keyword_field(self, field_name):
        """Determine if a field should use the .keyword subfield for exact matching.

        Uses precomputed field type information from the database model class for efficiency.
        """
        # Access the precomputed keyword fields from the database model class
        if self.database_model_cls is not None and hasattr(
            self.database_model_cls, "_keyword_fields"
        ):
            return field_name in self.database_model_cls._keyword_fields

        # Fallback: with explicit Keyword mappings, .keyword subfield is not needed
        # (only Text fields from custom models need .keyword)
        return False


@ESProvider.register_lookup
class Exact(DefaultLookup):
    """Exact Match Query"""

    lookup_name = "exact"

    def as_expression(self):
        # For exact matching on text fields, we need to use the .keyword subfield
        # which is automatically created by Elasticsearch for text fields
        field_name = self.process_source()

        # Use cached field type information to determine if .keyword suffix is needed
        if not field_name.endswith(".keyword") and self.should_use_keyword_field(
            field_name
        ):
            field_name = f"{field_name}.keyword"

        return query.Q("term", **{field_name: self.process_target()})


@ESProvider.register_lookup
class IExact(DefaultLookup):
    """Case-insensitive Exact Match Query"""

    lookup_name = "iexact"

    def as_expression(self):
        field_name = self.process_source()
        target_value = self.process_target()

        # Use case_insensitive flag on term query (works on Keyword fields)
        return query.Q(
            "term",
            **{field_name: {"value": target_value, "case_insensitive": True}},
        )


@ESProvider.register_lookup
class In(DefaultLookup):
    lookup_name = "in"

    def process_target(self):
        """Ensure target is a list or tuple"""
        assert isinstance(self.target, (list, tuple))
        return super().process_target()

    def as_expression(self):
        # For exact matching in lists, we need to use the .keyword subfield
        field_name = self.process_source()

        # Use cached field type information to determine if .keyword suffix is needed
        if not field_name.endswith(".keyword") and self.should_use_keyword_field(
            field_name
        ):
            field_name = f"{field_name}.keyword"

        return query.Q("terms", **{field_name: self.process_target()})


@ESProvider.register_lookup
class GreaterThan(DefaultLookup):
    lookup_name = "gt"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"gt": self.process_target()}}
        )


@ESProvider.register_lookup
class GreaterThanOrEqual(DefaultLookup):
    lookup_name = "gte"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"gte": self.process_target()}}
        )


@ESProvider.register_lookup
class LessThan(DefaultLookup):
    lookup_name = "lt"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"lt": self.process_target()}}
        )


@ESProvider.register_lookup
class LessThanOrEqual(DefaultLookup):
    lookup_name = "lte"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"lte": self.process_target()}}
        )


@ESProvider.register_lookup
class Contains(DefaultLookup):
    """Case-sensitive Contains Query"""

    lookup_name = "contains"

    def as_expression(self):
        # Wildcard queries work on keyword fields for exact case-sensitive matching
        field_name = self.process_source()

        # Use cached field type information to determine if .keyword suffix is needed
        if not field_name.endswith(".keyword") and self.should_use_keyword_field(
            field_name
        ):
            field_name = f"{field_name}.keyword"

        return query.Q(
            "wildcard",
            **{field_name: {"value": f"*{self.process_target()}*"}},
        )


@ESProvider.register_lookup
class IContains(DefaultLookup):
    """Case insensitive Contains Query"""

    lookup_name = "icontains"

    def as_expression(self):
        return query.Q(
            "wildcard",
            **{
                self.process_source(): {
                    "value": f"*{self.process_target()}*",
                    "case_insensitive": True,
                }
            },
        )


@ESProvider.register_lookup
class Startswith(DefaultLookup):
    lookup_name = "startswith"

    def as_expression(self):
        # Wildcard queries work on keyword fields
        field_name = self.process_source()

        # Use cached field type information to determine if .keyword suffix is needed
        if not field_name.endswith(".keyword") and self.should_use_keyword_field(
            field_name
        ):
            field_name = f"{field_name}.keyword"

        return query.Q(
            "wildcard",
            **{field_name: {"value": f"{self.process_target()}*"}},
        )


@ESProvider.register_lookup
class Endswith(DefaultLookup):
    lookup_name = "endswith"

    def as_expression(self):
        # Wildcard queries work on keyword fields
        field_name = self.process_source()

        # Use cached field type information to determine if .keyword suffix is needed
        if not field_name.endswith(".keyword") and self.should_use_keyword_field(
            field_name
        ):
            field_name = f"{field_name}.keyword"

        return query.Q(
            "wildcard",
            **{field_name: {"value": f"*{self.process_target()}"}},
        )


def register() -> None:
    """Register Elasticsearch provider with Protean if elasticsearch is available."""
    from protean.port.provider import registry

    try:
        import elasticsearch  # noqa: F401

        registry.register(
            "elasticsearch",
            "protean.adapters.repository.elasticsearch.ESProvider",
        )
        logger.debug("Elasticsearch provider registered successfully")
    except ImportError as e:
        logger.debug(
            f"Elasticsearch provider not registered: "
            f"elasticsearch package not available ({e})"
        )
