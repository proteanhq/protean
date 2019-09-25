"""Module containing repository implementation for Elasticsearch"""
# Standard Library Imports
import logging

from fnmatch import fnmatch
from typing import Any

import elasticsearch_dsl

from elasticsearch import Elasticsearch
from elasticsearch_dsl import Document, query, Search

from protean.core.field.association import Reference
from protean.core.provider.base import BaseProvider
from protean.core.repository.dao import BaseDAO
from protean.core.repository.lookup import BaseLookup
from protean.core.repository.resultset import ResultSet
from protean.globals import current_domain
from protean.utils import Database
from protean.utils.query import Q

logger = logging.getLogger('protean.repository')

operators = {
    'exact': '__eq__',
    'iexact': 'ilike',
    'contains': 'contains',
    'icontains': 'ilike',
    'startswith': 'startswith',
    'endswith': 'endswith',
    'gt': '__gt__',
    'gte': '__ge__',
    'lt': '__lt__',
    'lte': '__le__',
    'in': 'in_',
    'overlap': 'overlap',
    'any': 'any',
}


class ElasticsearchModel(Document):
    """A model for the Elasticsearch index"""

    @classmethod
    def from_entity(cls, entity) -> 'ElasticsearchModel':
        """Convert the entity to a Elasticsearch record """
        item_dict = {}
        for attribute_obj in cls.entity_cls.meta_.attributes.values():
            if isinstance(attribute_obj, Reference):
                item_dict[attribute_obj.relation.attribute_name] = \
                    attribute_obj.relation.value
            else:
                item_dict[attribute_obj.attribute_name] = getattr(
                    entity, attribute_obj.attribute_name)

        model_obj = cls(**item_dict)

        if 'id' in item_dict:
            model_obj.meta.id = model_obj.id
            del model_obj._d_['id']  # pylint: disable=W0212

        return model_obj

    @classmethod
    def to_entity(cls, item: 'ElasticsearchModel'):
        """Convert the elasticsearch document to an entity """
        item_dict = {}
        for field_name in cls.entity_cls.meta_.attributes:
            item_dict[field_name] = getattr(item, field_name, None)

        item_dict['id'] = item.meta.id
        entity_obj = cls.entity_cls(item_dict)

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
            # FIXME Implement OR condition
            pass

        return composed_query

    def _filter(self, criteria: Q, offset: int = 0, limit: int = 10,
                order_by: list = ()) -> ResultSet:
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

        # Return the results
        try:
            response = s.execute()
            result = ResultSet(
                offset=offset,
                limit=limit,
                total=len(response.hits),
                items=response.hits)
        except Exception as exc:
            logger.error(f"Error while filtering: {exc}")
            raise

        return result

    def _create(self, model_obj: Any):
        """Create a new model object from the entity"""
        conn = self._get_session()

        try:
            model_obj.save(refresh=True, index=model_obj.entity_cls.meta_.schema_name, using=conn)
        except Exception as exc:
            logger.error(f"Error while creating: {exc}")
            raise

        return model_obj

    def _update(self, model_obj: Any):
        """Update a model object in the data store and return it"""
        conn = self._get_session()

        try:
            model_obj.save(refresh=True, index=model_obj.entity_cls.meta_.schema_name, using=conn)
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
            model_obj.delete(refresh=True, index=model_obj.entity_cls.meta_.schema_name, using=conn)
        except Exception as exc:
            logger.error(f"Error while creating: {exc}")
            raise

        return model_obj

    def _delete_all(self, criteria: Q = None):
        """Delete a Record from the Repository"""
        raise NotImplementedError

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
        conn_info['DATABASE'] = Database.ELASTICSEARCH.value
        super().__init__(name, domain, conn_info)

        # A temporary cache of already constructed model classes
        self._model_classes = {}

    def _extract_lookup(self, key):
        """Extract lookup method based on key name format"""
        parts = key.rsplit('__', 1)

        if len(parts) == 1 or parts[1] not in operators:
            # 'exact' is the default lookup if there was no explicit comparison op in `key`
            op = 'exact'
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
        return Elasticsearch(self.conn_info['DATABASE_URI']['hosts'])

    def get_dao(self, entity_cls):
        """Return a DAO object configured with a live connection"""
        model_cls = self.get_model(entity_cls)
        return ElasticsearchDAO(self.domain, self, entity_cls, model_cls)

    def get_model(self, entity_cls):
        """Return a fully-baked Model class for a given Entity class"""
        model_cls = None

        if entity_cls.meta_.schema_name in self._model_classes:
            model_cls = self._model_classes[entity_cls.meta_.schema_name]
        else:
            attrs = {'entity_cls': entity_cls}
            model_cls = type(entity_cls.__name__ + 'Model', (ElasticsearchModel, ), attrs)

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
        conn = Elasticsearch()

        for _, aggregate_record in current_domain.aggregates.items():
            conn.delete_by_query(index=aggregate_record.cls.meta_.schema_name, body={"query": {"match_all": {}}})


@ESProvider.register_lookup
class Exact(BaseLookup):
    """Exact Match Query"""
    lookup_name = 'exact'
    lookup_type = 'filter'

    def as_expression(self):
        return query.Q('term', **{self.process_source(): self.process_target()})
