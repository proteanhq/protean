"""Implementation of a dictionary based repository """

# Standard Library Imports
import copy
import json

from collections import defaultdict
from datetime import datetime
from itertools import count
from operator import itemgetter
from threading import Lock
from typing import Any
from uuid import UUID

# Protean
from protean.core.exceptions import ObjectNotFoundError
from protean.core.provider.base import BaseProvider
from protean.core.repository.dao import BaseDAO
from protean.core.repository.lookup import BaseLookup
from protean.core.repository.model import BaseModel
from protean.core.repository.resultset import ResultSet
from protean.utils import Database
from protean.utils.query import Q

# Global in-memory store of dict data. Keyed by name, to provide
# multiple named local memory caches.
_databases = {}
_locks = {}
_counters = defaultdict(count)


class DictModel(BaseModel):
    """A model for the dictionary repository"""

    @classmethod
    def from_entity(cls, entity) -> 'DictModel':
        """Convert the entity to a dictionary record """
        dict_obj = {}
        for field_name in entity.meta_.attributes:
            dict_obj[field_name] = getattr(entity, field_name)
        return dict_obj

    @classmethod
    def to_entity(cls, item: 'DictModel'):
        """Convert the dictionary record to an entity """
        return cls.entity_cls(item)


class DictProvider(BaseProvider):
    """Provider class for Dict Repositories"""

    def __init__(self, name, domain, conn_info: dict):
        """Initialize Provider with Connection/Adapter details"""

        # In case of `DictProvider`, the `DATABASE` value will always be `MEMORY`.
        conn_info['DATABASE'] = Database.MEMORY.value
        super().__init__(name, domain, conn_info)

    def get_session(self):
        """Return a session object

        For Dictionary Repo, a session translates to a copy of the
        `database`. All transactions on the Provider's repositories
        are committed on this copy of the database.
        """
        _databases_copy = copy.deepcopy(_databases)
        database = {
            'data': _databases_copy.setdefault(self.name, defaultdict(dict)),
            'lock': _locks,
            'counters': _counters
        }
        return database

    def get_connection(self):
        """Return the dictionary database object """
        database = {
            'data': _databases.setdefault(self.name, defaultdict(dict)),
            'lock': _locks.setdefault(self.name, Lock()),
            'counters': defaultdict(count)
        }
        return database

    def commit(self, changes):
        global _databases, _locks, _counters

        for _, element in changes['ADDED'].items():
            dao = self.get_dao(element.__class__)
            dao.create(element.to_dict())

        for _, element in changes['UPDATED'].items():
            dao = self.get_dao(element.__class__)
            dao.update(element, element.to_dict())

        for _, element in changes['REMOVED'].items():
            dao = self.get_dao(element.__class__)
            dao.delete(element)

    def close_connection(self, conn):
        """Close connection does nothing on the repo """
        pass

    def _data_reset(self):
        """Reset data"""
        global _databases, _locks, _counters
        _databases = {}
        _locks = {}
        _counters = defaultdict(count)

    def get_model(self, entity_cls):
        """Return associated, fully-baked Model class"""
        cls = DictModel
        cls.entity_cls = entity_cls

        return cls

    def get_dao(self, entity_cls):
        """Return a DAO object configured with a live connection"""
        model_cls = self.get_model(entity_cls)
        return DictDAO(self.domain, self, entity_cls, model_cls)

    def _evaluate_lookup(self, key, value, negated, db):
        """Extract values from DB that match the given criteria"""
        results = {}
        for record_key, record_value in db.items():
            match = True

            stripped_key, lookup_class = self._extract_lookup(key)
            lookup = lookup_class(record_value[stripped_key], value)

            if record_value[stripped_key]:  # Do not evaluate if the value is None
                if negated:
                    match &= not eval(lookup.as_expression())
                else:
                    match &= eval(lookup.as_expression())
            else:
                match = False

            if match:
                results[record_key] = record_value

        return results

    def raw(self, query: Any, data: Any = None):
        """Run raw queries on the database

        As an example of running ``raw`` queries on a Dict repository, we will run the query
        on all possible schemas, and return all results.
        """
        assert isinstance(query, str)

        conn = self.get_connection()
        items = []

        for schema_name in conn['data']:
            input_db = conn['data'][schema_name]
            try:
                # Ensures that the string contains double quotes around keys and values
                query = query.replace("'", "\"")
                criteria = json.loads(query)

                for key, value in criteria.items():
                    input_db = self._evaluate_lookup(key, value, False, input_db)

                items.extend(list(input_db.values()))

            except json.JSONDecodeError:
                # FIXME Log Exception
                raise Exception("Query Malformed")
            except KeyError:
                # We encountered a repository where the key was not found
                pass

        return items


class DictDAO(BaseDAO):
    """A repository for storing data in a dictionary """

    def _set_auto_fields(self, model_obj):
        """Set the values of the auto field using counter"""
        conn = self.provider.get_connection()

        for field_name, field_obj in \
                self.entity_cls.meta_.auto_fields:
            counter_key = f'{self.schema_name}_{field_name}'
            if not (field_name in model_obj and model_obj[field_name] is not None):
                # Increment the counter and it should start from 1
                counter = next(conn['counters'][counter_key])
                if not counter:
                    counter = next(conn['counters'][counter_key])

                model_obj[field_name] = counter
        return model_obj

    def _create(self, model_obj):
        """Write a record to the dict repository"""
        conn = self.provider.get_connection()

        # Update the value of the counters
        model_obj = self._set_auto_fields(model_obj)

        # Add the entity to the repository
        identifier = model_obj[self.entity_cls.meta_.id_field.field_name]
        with conn['lock']:
            conn['data'][self.schema_name][identifier] = model_obj

        return model_obj

    def _filter_items(self, criteria: Q, db):
        """Recursive function to filter items from dictionary"""
        # Filter the dictionary objects based on the filters
        negated = criteria.negated
        input_db = None

        if criteria.connector == criteria.AND:
            # Trim database records over successive iterations
            #   Whatever is left at the end satisfy all criteria (AND)
            input_db = db
            for child in criteria.children:
                if isinstance(child, Q):
                    input_db = self._filter_items(child, input_db)
                else:
                    input_db = self.provider._evaluate_lookup(child[0], child[1],
                                                              negated, input_db)
        else:
            # Grow database records over successive iterations
            #   Whatever is left at the end satisfy any criteria (OR)
            input_db = {}
            for child in criteria.children:
                if isinstance(child, Q):
                    results = self._filter_items(child, db)
                else:
                    results = self.provider._evaluate_lookup(child[0], child[1], negated, db)

                input_db = {**input_db, **results}

        return input_db

    def _filter(self, criteria: Q, offset: int = 0, limit: int = 10, order_by: list = ()):
        """Read the repository and return results as per the filer"""
        conn = self.provider.get_connection()

        if criteria.children:
            items = list(self._filter_items(criteria, conn['data'][self.schema_name]).values())
        else:
            items = list(conn['data'][self.schema_name].values())

        # Sort the filtered results based on the order_by clause
        for o_key in order_by:
            reverse = False
            if o_key.startswith('-'):
                reverse = True
                o_key = o_key[1:]
            items = sorted(items, key=itemgetter(o_key), reverse=reverse)

        result = ResultSet(
            offset=offset,
            limit=limit,
            total=len(items),
            items=items[offset: offset + limit])
        return result

    def _update(self, model_obj):
        """Update the entity record in the dictionary """
        conn = self.provider.get_connection()

        identifier = model_obj[self.entity_cls.meta_.id_field.field_name]
        with conn['lock']:
            # Check if object is present
            if identifier not in conn['data'][self.schema_name]:
                raise ObjectNotFoundError(
                    f'`{self.__class__.__name__}` object with identifier {identifier} '
                    f'does not exist.')

            conn['data'][self.schema_name][identifier] = model_obj
        return model_obj

    def _update_all(self, criteria: Q, *args, **kwargs):
        """Update all objects satisfying the criteria """
        conn = self.provider.get_connection()

        items = self._filter_items(criteria, conn['data'][self.schema_name])

        update_count = 0
        for key in items:
            item = items[key]
            item.update(*args)
            item.update(kwargs)
            conn['data'][self.schema_name][key] = item

            update_count += 1

        return update_count

    def _delete(self, model_obj):
        """Delete the entity record in the dictionary """
        conn = self.provider.get_connection()

        identifier = model_obj[self.entity_cls.meta_.id_field.field_name]
        with conn['lock']:
            # Check if object is present
            if identifier not in conn['data'][self.schema_name]:
                raise ObjectNotFoundError(
                    f'`{self.entity_cls.__name__}` object with identifier {identifier} '
                    f'does not exist.')

            del conn['data'][self.schema_name][identifier]
        return model_obj

    def _delete_all(self, criteria: Q = None):
        """Delete the dictionary object by its criteria"""
        conn = self.provider.get_connection()
        if criteria:
            # Delete the object from the dictionary and return the deletion count
            items = self._filter_items(criteria, conn['data'][self.schema_name])

            # Delete all the matching identifiers
            with conn['lock']:
                for identifier in items:
                    conn['data'][self.schema_name].pop(identifier, None)

            return len(items)
        else:
            with conn['lock']:
                if self.schema_name in conn['data']:
                    del conn['data'][self.schema_name]

    def _raw(self, query: Any, data: Any = None):
        """Run raw query on Repository.

        For this stand-in repository, the query string is a json string that contains kwargs
        criteria with straigh-forward equality checks. Individual criteria are always ANDed
        and the result is always a subset of the full repository.

        We will ignore the `data` parameter for this kind of repository.
        """
        # Ensure that we are dealing with a string, for this repository
        assert isinstance(query, str)

        conn = self.provider.get_connection()
        input_db = conn['data'][self.schema_name]
        result = None

        try:
            # Ensures that the string contains double quotes around keys and values
            query = query.replace("'", "\"")
            criteria = json.loads(query)

            for key, value in criteria.items():
                input_db = self.provider._evaluate_lookup(key, value, False, input_db)

            items = list(input_db.values())
            result = ResultSet(
                offset=1,
                limit=len(items),
                total=len(items),
                items=items)

        except json.JSONDecodeError:
            # FIXME Log Exception
            raise Exception("Query Malformed")

        return result


operators = {
    'exact': '==',
    'iexact': '==',
    'contains': 'in',
    'icontains': 'in',
    'gt': '>',
    'gte': '>= ',
    'lt': '<',
    'lte': '<=',
    'in': 'in'
}


class DefaultDictLookup(BaseLookup):
    """Base class with default implementation of expression construction"""
    def process_source(self):
        """Return source with transformations, if any"""
        if isinstance(self.source, (UUID, datetime)):
            self.source = str(self.source)

        if isinstance(self.source, str):
            # Replace single and double quotes with escaped single-quote
            self.source = self.source.replace("'", "\'").replace('"', "\'")
            return "\"{source}\"".format(source=self.source)
        return self.source

    def process_target(self):
        """Return target with transformations, if any"""
        if isinstance(self.target, (UUID, datetime)):
            self.target = str(self.target)

        if isinstance(self.target, str):
            # Replace single and double quotes with escaped single-quote
            self.target = self.target.replace("'", "\'").replace('"', "\'")
            return "\"{target}\"".format(target=self.target)
        return self.target

    def as_expression(self):
        return '{source} {op} {target}'.format(source=self.process_source(),
                                               op=operators[self.lookup_name],
                                               target=self.process_target())


@DictProvider.register_lookup
class Exact(DefaultDictLookup):
    """Exact Match Query"""
    lookup_name = 'exact'


@DictProvider.register_lookup
class IExact(DefaultDictLookup):
    """Exact Case-Insensitive Match Query"""
    lookup_name = 'iexact'

    def process_source(self):
        """Return source in lowercase"""
        assert isinstance(self.source, str)
        return "%s.lower()" % super().process_source()

    def process_target(self):
        """Return target in lowercase"""
        assert isinstance(self.target, str)
        return "%s.lower()" % super().process_target()


@DictProvider.register_lookup
class Contains(DefaultDictLookup):
    """Exact Contains Query"""
    lookup_name = 'contains'

    def as_expression(self):
        """Check for Target string to be in Source string"""
        return '%s %s %s' % (self.process_target(),
                             operators[self.lookup_name],
                             self.process_source())


@DictProvider.register_lookup
class IContains(DefaultDictLookup):
    """Exact Case-Insensitive Contains Query"""
    lookup_name = 'icontains'

    def process_source(self):
        """Return source in lowercase"""
        assert isinstance(self.source, str)
        return "%s.lower()" % super().process_source()

    def process_target(self):
        """Return target in lowercase"""
        assert isinstance(self.target, str)
        return "%s.lower()" % super().process_target()

    def as_expression(self):
        """Check for Target string to be in Source string"""
        return '%s %s %s' % (self.process_target(),
                             operators[self.lookup_name],
                             self.process_source())


@DictProvider.register_lookup
class GreaterThan(DefaultDictLookup):
    """Greater than Query"""
    lookup_name = 'gt'


@DictProvider.register_lookup
class GreaterThanOrEqual(DefaultDictLookup):
    """Greater than or Equal Query"""
    lookup_name = 'gte'


@DictProvider.register_lookup
class LessThan(DefaultDictLookup):
    """Less than Query"""
    lookup_name = 'lt'


@DictProvider.register_lookup
class LessThanOrEqual(DefaultDictLookup):
    """Less than or Equal Query"""
    lookup_name = 'lte'


@DictProvider.register_lookup
class In(DefaultDictLookup):
    """In Query"""
    lookup_name = 'in'

    def process_target(self):
        """Ensure target is a list or tuple"""
        assert type(self.target) in (list, tuple)
        return super().process_target()
