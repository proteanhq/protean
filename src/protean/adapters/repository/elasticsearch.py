"""Module containing repository implementation for Elasticsearch"""
import logging

from typing import Any
from uuid import UUID

import elasticsearch_dsl

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
from elasticsearch_dsl import Document, Index, Search, query

from protean.core.field.association import Reference
from protean.exceptions import ObjectNotFoundError
from protean.globals import current_domain
from protean.port.dao import BaseDAO, BaseLookup, ResultSet
from protean.port.provider import BaseProvider
from protean.utils import Database, IdentityStrategy, IdentityType
from protean.utils.query import Q

logger = logging.getLogger("protean.repository")

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


def derive_schema_name(model_cls):
    if hasattr(model_cls.meta_, "schema_name"):
        return model_cls.meta_.schema_name
    else:
        return model_cls.meta_.entity_cls.meta_.schema_name


class ElasticsearchModel(Document):
    """A model for the Elasticsearch index"""

    @classmethod
    def from_entity(cls, entity) -> "ElasticsearchModel":
        """Convert the entity to a Elasticsearch record """
        item_dict = {}
        for attribute_obj in cls.meta_.entity_cls.meta_.attributes.values():
            if isinstance(attribute_obj, Reference):
                item_dict[
                    attribute_obj.relation.attribute_name
                ] = attribute_obj.relation.value
            else:
                item_dict[attribute_obj.attribute_name] = getattr(
                    entity, attribute_obj.attribute_name
                )

        model_obj = cls(**item_dict)

        if "id" in item_dict:
            model_obj.meta.id = model_obj.id
            del model_obj._d_["id"]  # pylint: disable=W0212

        return model_obj

    @classmethod
    def to_entity(cls, item: "ElasticsearchModel"):
        """Convert the elasticsearch document to an entity """
        item_dict = {}

        # Convert the values in ES Model as a dictionary
        values = item.to_dict()
        for field_name in cls.meta_.entity_cls.meta_.attributes:
            item_dict[field_name] = values.get(field_name, None)

        identifier = None
        if (
            current_domain.config["IDENTITY_STRATEGY"] == IdentityStrategy.UUID.value
            and current_domain.config["IDENTITY_TYPE"] == IdentityType.UUID.value
            and isinstance(item.meta.id, str)
        ):
            identifier = UUID(item.meta.id)
        else:
            identifier = item.meta.id

        item_dict["id"] = identifier
        entity_obj = cls.meta_.entity_cls(item_dict)

        return entity_obj


class ESSession:
    """A Session wrapper for Elasticsearch Database.

    Elasticsearch does not support Transactions or Sessions, so this class is
    essential a no-op, and acts as a passthrough for all transactions.
    """

    def __init__(self, provider, new_connection=False):
        self._provider = provider

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

    def get(self, identifier: Any):
        """Retrieve a specific Record from the Repository by its `identifier`.

        This method internally uses the `filter` method to fetch records.

        Returns exactly one record that matches the identifier.

        Throws `ObjectNotFoundError` if no record was found for the identifier.

        Throws `TooManyObjectsError` if multiple records were found for the identifier.

        :param identifier: id of the record to be fetched from the data store.
        """
        logger.debug(
            f"Lookup `{self.entity_cls.__name__}` object with identifier {identifier}"
        )

        conn = self._get_session()
        result = None

        try:
            result = self.model_cls.get(
                id=identifier, using=conn, index=self.entity_cls.meta_.schema_name
            )
        except NotFoundError:
            logger.error(f"Record {identifier} was not found")
            raise ObjectNotFoundError(
                {
                    "entity": f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                    f"does not exist."
                }
            )
        except Exception as error:
            logger.error(f"Unknown error occurred when fetching {identifier}: {error}")
            raise (
                f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        entity = self.model_cls.to_entity(result)
        return entity

    def _build_filters(self, criteria: Q):
        """ Recursively Build the filters from the criteria object"""
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
        conn = self._get_session()

        # Build the filters from the criteria
        q = elasticsearch_dsl.Q()
        if criteria.children:
            q = self._build_filters(criteria)

        s = Search(using=conn, index=self.entity_cls.meta_.schema_name).query(q)

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
        conn = self._get_session()

        try:
            model_obj.save(
                refresh=True,
                index=model_obj.meta_.entity_cls.meta_.schema_name,
                using=conn,
            )
        except Exception as exc:
            logger.error(f"Error while creating: {exc}")
            raise

        return model_obj

    def _update(self, model_obj: Any):
        """Update a model object in the data store and return it"""
        conn = self._get_session()

        identifier = model_obj.meta.id

        # Fetch the record from database
        try:
            # Calling `get` will raise `NotFoundError` if record was not found
            self.model_cls.get(
                id=identifier, using=conn, index=self.entity_cls.meta_.schema_name
            )
        except NotFoundError as exc:
            logger.error(f"Database Record not found: {exc}")
            raise ObjectNotFoundError(
                {
                    "entity": f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                    f"does not exist."
                }
            )

        try:
            model_obj.save(
                refresh=True,
                index=model_obj.meta_.entity_cls.meta_.schema_name,
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
                index=model_obj.meta_.entity_cls.meta_.schema_name,
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

        s = Search(using=conn, index=self.entity_cls.meta_.schema_name).query(q)

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
    def __init__(self, name, domain, conn_info: dict):
        """Initialize Provider with Connection/Adapter details"""

        # In case of `ESProvider`, the `DATABASE` value will always be `ELASTICSEARCH`.
        conn_info["DATABASE"] = Database.ELASTICSEARCH.value
        super().__init__(name, domain, conn_info)

        # A temporary cache of already constructed model classes
        self._model_classes = {}

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
            self.conn_info["DATABASE_URI"]["hosts"],
            use_ssl=self.conn_info.get("USE_SSL", False),
            verify_certs=self.conn_info.get("VERIFY_CERTS", False),
        )

    def get_dao(self, entity_cls, model_cls):
        """Return a DAO object configured with a live connection"""
        return ElasticsearchDAO(self.domain, self, entity_cls, model_cls)

    def decorate_model_class(self, entity_cls, model_cls):
        schema_name = derive_schema_name(model_cls)

        # Return the model class if it was already seen/decorated
        if schema_name in self._model_classes:
            return self._model_classes[schema_name]

        # If `model_cls` is already subclassed from SqlAlchemyModel,
        #   this method call is a no-op
        if issubclass(model_cls, ElasticsearchModel):
            return model_cls
        else:
            custom_attrs = {
                key: value
                for (key, value) in vars(model_cls).items()
                if key not in ["Meta", "__module__", "__doc__", "__weakref__"]
            }

            from protean.core.model import ModelMeta

            meta_ = ModelMeta()
            meta_.entity_cls = entity_cls

            custom_attrs.update({"meta_": meta_})
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
            from protean.core.model import ModelMeta

            meta_ = ModelMeta()
            meta_.entity_cls = entity_cls

            attrs = {
                "meta_": meta_,
            }
            # FIXME Ensure the custom model attributes are constructed properly
            model_cls = type(
                entity_cls.__name__ + "Model", (ElasticsearchModel,), attrs
            )

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

        for _, aggregate_record in current_domain.registry.aggregates.items():
            provider = current_domain.get_provider(aggregate_record.cls.meta_.provider)
            if provider.conn_info["DATABASE"] == Database.ELASTICSEARCH.value:
                conn.delete_by_query(
                    refresh=True,
                    index=aggregate_record.cls.meta_.schema_name,
                    body={"query": {"match_all": {}}},
                )


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
    """In Match Query"""

    lookup_name = "in"

    def process_target(self):
        """Ensure target is a list or tuple"""
        assert isinstance(self.target, (list, tuple))
        return super().process_target()

    def as_expression(self):
        return query.Q("terms", **{self.process_source(): self.process_target()})


@ESProvider.register_lookup
class GreaterThan(DefaultLookup):
    """Greater than Query"""

    lookup_name = "gt"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"gt": self.process_target()}}
        )


@ESProvider.register_lookup
class GreaterThanOrEqual(DefaultLookup):
    """Greater than or Equal Query"""

    lookup_name = "gte"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"gte": self.process_target()}}
        )


@ESProvider.register_lookup
class LessThan(DefaultLookup):
    """Less than Query"""

    lookup_name = "lt"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"lt": self.process_target()}}
        )


@ESProvider.register_lookup
class LessThanOrEqual(DefaultLookup):
    """Less than or Equal Query"""

    lookup_name = "lte"

    def as_expression(self):
        return query.Q(
            "range", **{self.process_source(): {"lte": self.process_target()}}
        )


@ESProvider.register_lookup
class Contains(DefaultLookup):
    """Exact Contains Query"""

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
    """Exact Contains Query"""

    lookup_name = "startswith"

    def as_expression(self):
        return query.Q(
            "wildcard",
            **{self.process_source(): {"value": f"{self.process_target()}*"}},
        )


@ESProvider.register_lookup
class Endswith(DefaultLookup):
    """Exact Contains Query"""

    lookup_name = "endswith"

    def as_expression(self):
        return query.Q(
            "wildcard",
            **{self.process_source(): {"value": f"*{self.process_target()}"}},
        )
