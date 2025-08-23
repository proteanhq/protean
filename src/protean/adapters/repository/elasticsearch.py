"""Module containing repository implementation for Elasticsearch"""

import json
import logging
from typing import Any
from uuid import UUID

import elasticsearch_dsl
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
from elasticsearch_dsl import Document, Index, Keyword, Mapping, Search, query

from protean.core.queryset import ResultSet
from protean.exceptions import DatabaseError, ObjectNotFoundError
from protean.fields import Reference
from protean.port.dao import BaseDAO, BaseLookup
from protean.port.provider import BaseProvider
from protean.utils import IdentityStrategy, IdentityType
from protean.utils.container import Options
from protean.utils.globals import current_domain, current_uow
from protean.utils.query import Q
from protean.utils.reflection import attributes, id_field
from protean.fields import Integer, Float, Boolean, DateTime, Date, Auto, Identifier

logger = logging.getLogger(__name__)

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


class ElasticsearchModel(Document):
    """A database model for the Elasticsearch index"""

    @classmethod
    def from_entity(cls, entity) -> "ElasticsearchModel":
        """Convert the entity to a Elasticsearch record"""
        item_dict = {}
        for attribute_obj in attributes(cls.meta_.part_of).values():
            if isinstance(attribute_obj, Reference):
                item_dict[attribute_obj.relation.attribute_name] = (
                    attribute_obj.relation.value
                )
            else:
                attr_name = attribute_obj.attribute_name
                attr_value = getattr(entity, attr_name)
                # Store entity version as 'entity_version' to avoid conflict with ES _version
                # FIXME Make this more robust and database implementation resistant
                if attr_name == "_version":
                    item_dict["entity_version"] = attr_value
                else:
                    item_dict[attr_name] = attr_value

        model_obj = cls(**item_dict)

        # Elasticsearch stores identity in a special field `meta.id`.
        # Set `meta.id` to the identifier set in entity
        id_field_name = id_field(cls.meta_.part_of).field_name

        if id_field_name in item_dict:
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
        id_field_name = id_field(cls.meta_.part_of).field_name
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

    def add(self, element):
        dao = self._provider.get_dao(element.__class__)
        dao.create(element.to_dict())

    def delete(self, element):
        dao = self._provider.get_dao(element.__class__)
        dao.delete(element)

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
                    lookup = lookup_class(stripped_key, child[1])
                    # Pass database model class to lookup for cached field type information
                    lookup.database_model_cls = self.database_model_cls
                    if criteria.negated:
                        composed_query = composed_query & ~lookup.as_expression()
                    else:
                        composed_query = composed_query & lookup.as_expression()
        else:
            for child in criteria.children:
                if isinstance(child, Q):
                    composed_query = composed_query | self._build_filters(child)
                else:
                    stripped_key, lookup_class = self.provider._extract_lookup(child[0])
                    lookup = lookup_class(stripped_key, child[1])
                    # Pass database model class to lookup for cached field type information
                    lookup.database_model_cls = self.database_model_cls
                    if criteria.negated:
                        composed_query = composed_query | ~lookup.as_expression()
                    else:
                        composed_query = composed_query | lookup.as_expression()

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
                model_obj = self.database_model_cls(**hit.to_dict())
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
                        model_obj = self.database_model_cls(**hit.to_dict())
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

    def _update(self, model_obj: Any):
        """Update a database model object in the data store and return it"""
        conn = self.provider.get_connection()

        identifier = model_obj.meta.id

        # Fetch the record from database
        try:
            # Calling `get` will raise `NotFoundError` if record was not found
            self.database_model_cls.get(
                id=identifier, using=conn, index=self.database_model_cls._index._name
            )
        except NotFoundError as exc:
            logger.error(f"Database Record not found: {exc}")
            raise ObjectNotFoundError(
                f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        try:
            model_obj.save(
                refresh=True,
                index=self.database_model_cls._index._name,
                using=conn,
            )
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
            identifier = getattr(model_obj, id_field(self.entity_cls).attribute_name)
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
        """Run raw query on Data source.

        Running a raw query on the data store should always returns entity instance objects. If
        the results were not synthesizable back into entity objects, an exception should be thrown.
        """
        raise NotImplementedError

    def has_table(self) -> bool:
        """Check if the index exists in Elasticsearch.

        Returns True if the index exists, False otherwise.
        """
        conn = self.provider.get_connection()
        return conn.indices.exists(index=self.database_model_cls._index._name)


class ESProvider(BaseProvider):
    __database__ = "elasticsearch"

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

    def _compute_keyword_fields(self, entity_cls):
        """Precompute which fields should use .keyword subfield for exact matching.

        Returns a set of field names that should use the .keyword subfield.
        This computation is done once during model construction for efficiency.
        """
        keyword_fields = set()
        entity_attributes = attributes(entity_cls)

        for field_name, field_obj in entity_attributes.items():
            # Numeric and date fields should not use .keyword subfield
            # They are mapped as their native types (long, double, date) in Elasticsearch
            numeric_and_date_types = (Integer, Float, Boolean, DateTime, Date)
            if isinstance(field_obj, numeric_and_date_types):
                continue

            # Identifier fields are explicitly mapped as keyword type, so don't need .keyword suffix
            if isinstance(field_obj, (Auto, Identifier)) or getattr(
                field_obj, "identifier", False
            ):
                continue

            # All other fields (String, Text, etc.) should use .keyword for exact matching
            keyword_fields.add(field_name)

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

        # Return the model class if it was already seen/decorated
        if schema_name in self._database_model_classes:
            return self._database_model_classes[schema_name]

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

            # FIXME Ensure the custom model attributes are constructed properly
            decorated_database_database_model_cls = type(
                database_model_cls.__name__,
                (ElasticsearchModel, database_model_cls),
                custom_attrs,
            )

            # Precompute and cache field type information for efficient lookup operations
            keyword_fields = self._compute_keyword_fields(entity_cls)
            decorated_database_database_model_cls._keyword_fields = keyword_fields

            # Memoize the constructed model class
            self._database_model_classes[schema_name] = (
                decorated_database_database_model_cls
            )

            return decorated_database_database_model_cls

    def construct_database_model_class(self, entity_cls):
        """Return a fully-baked Model class for a given Entity class"""
        database_model_cls = None
        schema_name = self.namespaced_schema_name(entity_cls.meta_.schema_name)

        # Return the model class if it was already seen/decorated
        if schema_name in self._database_model_classes:
            database_model_cls = self._database_model_classes[schema_name]
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

            # FIXME Ensure the custom model attributes are constructed properly
            database_model_cls = type(
                entity_cls.__name__ + "Model", (ElasticsearchModel,), attrs
            )

            # Create Dynamic Mapping and associate with index
            # FIXME Expand to all types of fields
            id_field_name = id_field(entity_cls).field_name
            m = Mapping()
            m.field(id_field_name, Keyword())

            database_model_cls._index.mapping(m)

            # Precompute and cache field type information for efficient lookup operations
            keyword_fields = self._compute_keyword_fields(entity_cls)
            database_model_cls._keyword_fields = keyword_fields

            # Memoize the constructed model class
            self._database_model_classes[schema_name] = database_model_cls

        # Set Entity Class as a class level attribute for the Model, to be able to reference later.
        return database_model_cls

    def raw(self, query: Any, data: Any = None):
        """Run raw query directly on the database

        Query should be executed immediately on the database as a separate unit of work
            (in a different transaction context). The results should be returned as returned by
            the database without any intervention. It is left to the consumer to interpret and
            organize the results correctly.
        """
        raise NotImplementedError

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
            provider = current_domain.providers[element_record.cls.meta_.provider]
            repo = self.domain.repository_for(element_record.cls)

            database_model_cls = repo._database_model
            if (
                provider.__class__.__database__ == "elasticsearch"
                and conn.indices.exists(index=database_model_cls._index._name)
            ):
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
            provider = current_domain.providers[element_record.cls.meta_.provider]
            database_model_cls = current_domain.repository_for(
                element_record.cls
            )._database_model
            if (
                provider.__class__.__database__ == "elasticsearch"
                and not database_model_cls._index.exists(using=conn)
            ):
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
            database_model_cls = self.domain.repository_for(
                element_record.cls
            )._database_model
            provider = self.domain.providers[element_record.cls.meta_.provider]
            if (
                provider.__class__.__database__ == "elasticsearch"
                and database_model_cls._index.exists(using=conn)
            ):
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
        if hasattr(self, "database_model_cls") and hasattr(
            self.database_model_cls, "_keyword_fields"
        ):
            return field_name in self.database_model_cls._keyword_fields

        # Fallback: if we don't have the cached info, default to using .keyword for safety
        return True


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
        # For case-insensitive exact matching, we use the analyzed text field
        # which has been lowercased by the default analyzer
        field_name = self.process_source()
        target_value = self.process_target()

        # Convert target to lowercase to match the analyzed field
        if isinstance(target_value, str):
            target_value = target_value.lower()

        return query.Q("term", **{field_name: target_value})


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
