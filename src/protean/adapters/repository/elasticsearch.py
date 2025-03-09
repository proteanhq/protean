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
from protean.exceptions import ObjectNotFoundError
from protean.fields import Reference
from protean.port.dao import BaseDAO, BaseLookup
from protean.port.provider import BaseProvider
from protean.utils import IdentityStrategy, IdentityType
from protean.utils.container import Options
from protean.utils.globals import current_domain
from protean.utils.query import Q
from protean.utils.reflection import attributes, id_field

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
    """A model for the Elasticsearch index"""

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
                item_dict[attribute_obj.attribute_name] = getattr(
                    entity, attribute_obj.attribute_name
                )

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

        # Set version from document meta, only if `_version` attr is present
        if hasattr(cls.meta_.part_of, "_version"):
            item_dict["_version"] = item.meta.version

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
            Search(using=conn, index=self.model_cls._index._name)
            .query(q)
            .params(version=True)
        )

        if order_by:
            s = s.sort(*order_by)

        s = s[offset : offset + limit]

        # Return the results
        try:
            response = s.execute()
            result = ResultSet(
                offset=offset,
                limit=limit,
                total=response.hits.total.value,
                items=response.hits,
            )
        except Exception as exc:
            logger.error(f"Error while filtering: {exc}")
            raise

        return result

    def _create(self, model_obj: Any):
        """Create a new model object from the entity"""
        conn = self.provider.get_connection()

        try:
            model_obj.save(
                refresh=True,
                index=self.model_cls._index._name,
                using=conn,
            )
        except Exception as exc:
            logger.error(f"Error while creating: {exc}")
            raise

        return model_obj

    def _update(self, model_obj: Any):
        """Update a model object in the data store and return it"""
        conn = self.provider.get_connection()

        identifier = model_obj.meta.id

        # Fetch the record from database
        try:
            # Calling `get` will raise `NotFoundError` if record was not found
            self.model_cls.get(
                id=identifier, using=conn, index=self.model_cls._index._name
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
                index=self.model_cls._index._name,
                using=conn,
            )
        except Exception as exc:
            logger.error(f"Error while creating: {exc}")
            raise

        return model_obj

    def _update_all(self, criteria: Q, *args, **kwargs):
        """Updates object directly in the data store and returns update count"""
        raise NotImplementedError

    def _delete(self, model_obj):
        """Delete a Record from the Repository"""
        conn = self._get_session()

        try:
            model_obj.delete(
                index=self.model_cls._index._name,
                using=conn,
                refresh=True,
            )
        except Exception as exc:
            logger.error(f"Error while creating: {exc}")
            raise

        return model_obj

    def _delete_all(self, criteria: Q = None):
        """Delete all records matching criteria from the Repository"""
        conn = self._get_session()

        # Build the filters from the criteria
        q = elasticsearch_dsl.Q()
        if criteria and criteria.children:
            q = self._build_filters(criteria)

        s = Search(using=conn, index=self.model_cls._index._name).query(q)

        # Return the results
        try:
            response = s.delete()

            # `Search.delete` does not refresh index, so we have to manually refresh
            index = Index(name=self.entity_cls.meta_.schema_name, using=conn)
            index.refresh()
        except Exception as exc:
            logger.error(f"Error while deleting records: {exc}")
            raise

        return response.deleted

    def _raw(self, query: Any, data: Any = None):
        """Run raw query on Data source.

        Running a raw query on the data store should always returns entity instance objects. If
        the results were not synthesizable back into entity objects, an exception should be thrown.
        """
        raise NotImplementedError


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
        self._model_classes = {}

    def derive_schema_name(self, entity_cls):
        schema_name = entity_cls.meta_.schema_name

        # Prepend Namespace prefix if one has been provided
        if "NAMESPACE_PREFIX" in self.conn_info and self.conn_info["NAMESPACE_PREFIX"]:
            # Use custom separator if provided
            separator = "_"
            if (
                "NAMESPACE_SEPARATOR" in self.conn_info
                and self.conn_info["NAMESPACE_SEPARATOR"]
            ):
                separator = self.conn_info["NAMESPACE_SEPARATOR"]

            schema_name = f"{self.conn_info['NAMESPACE_PREFIX']}{separator}{entity_cls.meta_.schema_name}"

        return schema_name

    def _extract_lookup(self, key):
        """Extract lookup method based on key name format"""
        parts = key.rsplit("__", 1)

        if len(parts) > 1 and parts[1] in operators:
            op = parts[1]
            attribute = parts[0]
        else:
            # 'exact' is the default lookup if there was no explicit comparison op in `key`
            op = "exact"
            attribute = key

        # Construct and assign the lookup class as a filter criteria
        return attribute, self.get_lookup(op)

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

        return Elasticsearch(
            self.conn_info["database_uri"]["hosts"],
            use_ssl=self.conn_info.get("USE_SSL", False),
            verify_certs=self.conn_info.get("VERIFY_CERTS", False),
        )

    def is_alive(self) -> bool:
        """Check if the connection is alive"""
        conn = self.get_connection()
        return conn.ping()

    def get_dao(self, entity_cls, model_cls):
        """Return a DAO object configured with a live connection"""
        return ElasticsearchDAO(self.domain, self, entity_cls, model_cls)

    def decorate_model_class(self, entity_cls, model_cls):
        schema_name = self.derive_schema_name(entity_cls)

        # Return the model class if it was already seen/decorated
        if schema_name in self._model_classes:
            return self._model_classes[schema_name]

        # If `model_cls` is already subclassed from ElasticsearchModel,
        #   this method call is a no-op
        if issubclass(model_cls, ElasticsearchModel):
            return model_cls
        else:
            custom_attrs = {
                key: value
                for (key, value) in vars(model_cls).items()
                if key not in ["Meta", "__module__", "__doc__", "__weakref__"]
            }

            # Construct Inner Index class with options
            options = {}

            # Set schema name intelligently
            #   model_cls.meta_.schema_name - would come from custom model's options
            #   model_cls._index._name - would come from custom model's `Index` inner class
            #   schema_name - is derived
            index_name = (
                model_cls._index._name if hasattr(model_cls, "_index") else None
            )
            options["name"] = model_cls.meta_.schema_name or index_name or schema_name

            # Gather adapter settings
            if "SETTINGS" in self.conn_info and self.conn_info["SETTINGS"]:
                options["settings"] = self.conn_info["SETTINGS"]

            # Set options into `Index` inner class for ElasticsearchModel
            index_cls = type("Index", (object,), options)

            # Add the Index class to the custom attributes
            custom_attrs.update({"Index": index_cls})

            # FIXME Ensure the custom model attributes are constructed properly
            decorated_model_cls = type(
                model_cls.__name__, (ElasticsearchModel, model_cls), custom_attrs
            )

            # Memoize the constructed model class
            self._model_classes[schema_name] = decorated_model_cls

            return decorated_model_cls

    def construct_model_class(self, entity_cls):
        """Return a fully-baked Model class for a given Entity class"""
        model_cls = None

        # Return the model class if it was already seen/decorated
        if entity_cls.meta_.schema_name in self._model_classes:
            model_cls = self._model_classes[entity_cls.meta_.schema_name]
        else:
            meta_ = Options()
            meta_.part_of = entity_cls

            # Construct Inner Index class with options
            options = {}
            options["name"] = self.derive_schema_name(entity_cls)
            if "SETTINGS" in self.conn_info and self.conn_info["SETTINGS"]:
                options["settings"] = self.conn_info["SETTINGS"]

            index_cls = type("Index", (object,), options)

            attrs = {"meta_": meta_, "Index": index_cls}

            # FIXME Ensure the custom model attributes are constructed properly
            model_cls = type(
                entity_cls.__name__ + "Model", (ElasticsearchModel,), attrs
            )

            # Create Dynamic Mapping and associate with index
            # FIXME Expand to all types of fields
            id_field_name = id_field(entity_cls).field_name
            m = Mapping()
            m.field(id_field_name, Keyword())

            model_cls._index.mapping(m)

            # Memoize the constructed model class
            self._model_classes[entity_cls.meta_.schema_name] = model_cls

        # Set Entity Class as a class level attribute for the Model, to be able to reference later.
        return model_cls

    def raw(self, query: Any, data: Any = None):
        """Run raw query directly on the database

        Query should be executed immediately on the database as a separate unit of work
            (in a different transaction context). The results should be returned as returned by
            the database without any intervention. It is left to the consumer to interpret and
            organize the results correctly.
        """
        raise NotImplementedError

    def _data_reset(self):
        """Utility method to reset data in DB between tests"""
        conn = self.get_connection()

        elements = {
            **self.domain.registry.aggregates,
            **self.domain.registry.entities,
            **self.domain.registry.views,
        }
        for _, element_record in elements.items():
            provider = current_domain.providers[element_record.cls.meta_.provider]
            repo = self.domain.repository_for(element_record.cls)

            model_cls = repo._model
            if (
                provider.__class__.__database__ == "elasticsearch"
                and conn.indices.exists(index=model_cls._index._name)
            ):
                conn.delete_by_query(
                    refresh=True,
                    index=model_cls._index._name,
                    body={"query": {"match_all": {}}},
                )

    def _create_database_artifacts(self):
        conn = self.get_connection()

        elements = {
            **self.domain.registry.aggregates,
            **self.domain.registry.entities,
            **self.domain.registry.views,
        }
        for _, element_record in elements.items():
            provider = current_domain.providers[element_record.cls.meta_.provider]
            model_cls = current_domain.repository_for(element_record.cls)._model
            if (
                provider.__class__.__database__ == "elasticsearch"
                and not model_cls._index.exists(using=conn)
            ):
                # We use model_cls here to ensure the index is created along with mappings
                model_cls.init(using=conn)

    def _drop_database_artifacts(self):
        conn = self.get_connection()

        elements = {
            **self.domain.registry.aggregates,
            **self.domain.registry.entities,
            **self.domain.registry.views,
        }
        for _, element_record in elements.items():
            model_cls = self.domain.repository_for(element_record.cls)._model
            provider = self.domain.providers[element_record.cls.meta_.provider]
            if (
                provider.__class__.__database__ == "elasticsearch"
                and model_cls._index.exists(using=conn)
            ):
                conn.indices.delete(index=model_cls._index._name)


class DefaultLookup(BaseLookup):
    """Base class with default implementation of expression construction"""

    def process_target(self):
        """Return target with transformations, if any"""
        if isinstance(self.target, UUID):
            self.target = str(self.target)

        return self.target


@ESProvider.register_lookup
class Exact(DefaultLookup):
    """Exact Match Query"""

    lookup_name = "exact"

    def as_expression(self):
        return query.Q("term", **{self.process_source(): self.process_target()})


@ESProvider.register_lookup
class In(DefaultLookup):
    lookup_name = "in"

    def process_target(self):
        """Ensure target is a list or tuple"""
        assert isinstance(self.target, (list, tuple))
        return super().process_target()

    def as_expression(self):
        return query.Q("terms", **{self.process_source(): self.process_target()})


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
        return query.Q(
            "wildcard",
            **{self.process_source(): {"value": f"*{self.process_target()}*"}},
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
        return query.Q(
            "wildcard",
            **{self.process_source(): {"value": f"{self.process_target()}*"}},
        )


@ESProvider.register_lookup
class Endswith(DefaultLookup):
    lookup_name = "endswith"

    def as_expression(self):
        return query.Q(
            "wildcard",
            **{self.process_source(): {"value": f"*{self.process_target()}"}},
        )
