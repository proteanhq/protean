""" Implementation of a dictionary based repository """

from collections import defaultdict
from itertools import count
from operator import itemgetter
from threading import Lock

from protean.core.entity import Q
from protean.core.exceptions import ObjectNotFoundError
from protean.core.provider.base import BaseProvider
from protean.core.repository import BaseLookup
from protean.core.repository import BaseModel
from protean.core.repository import BaseRepository
from protean.core.repository import Pagination

# Global in-memory store of dict data. Keyed by name, to provide
# multiple named local memory caches.
_databases = {}
_locks = {}
_counters = defaultdict(count)


class DictProvider(BaseProvider):
    """Provider class for Dict Repositories"""

    def get_session(self):
        """Return a session object

        FIXME Is it possible to simulate transactions with Dict Repo?
        Maybe we should to be able to simulate Unit of Work transactions
        """
        pass

    def get_connection(self):
        """ Return the dictionary database object """
        database = {
            'data': _databases.setdefault(self.identifier, defaultdict(dict)),
            'lock': _locks.setdefault(self.identifier, Lock()),
            'counters': _counters
        }
        return database

    def close_connection(self, conn):
        """ Close connection does nothing on the repo """
        pass

    def get_repository(self, model_cls):
        """ Return a repository object configured with a live connection"""
        return DictRepository(self, model_cls)


class DictRepository(BaseRepository):
    """ A repository for storing data in a dictionary """

    def _set_auto_fields(self, model_obj):
        """ Set the values of the auto field using counter"""
        for field_name, field_obj in \
                self.entity_cls.meta_.auto_fields:
            counter_key = f'{self.model_name}_{field_name}'
            if not (field_name in model_obj and model_obj[field_name] is not None):
                # Increment the counter and it should start from 1
                counter = next(self.conn['counters'][counter_key])
                if not counter:
                    counter = next(self.conn['counters'][counter_key])

                model_obj[field_name] = counter
        return model_obj

    def _create_object(self, model_obj):
        """ Write a record to the dict repository"""
        # Update the value of the counters
        model_obj = self._set_auto_fields(model_obj)

        # Add the entity to the repository
        identifier = model_obj[self.entity_cls.meta_.id_field.field_name]
        with self.conn['lock']:
            self.conn['data'][self.model_name][identifier] = model_obj

        return model_obj

    def _evaluate_lookup(self, key, value, negated, db):
        """Extract values from DB that match the given criteria"""
        results = {}
        for record_key, record_value in db.items():
            match = True

            stripped_key, lookup_class = self.provider._extract_lookup(key)
            lookup = lookup_class(record_value[stripped_key], value)

            if negated:
                match &= not eval(lookup.as_expression())
            else:
                match &= eval(lookup.as_expression())

            if match:
                results[record_key] = record_value

        return results

    def _filter(self, criteria: Q, db):
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
                    input_db = self._filter(child, input_db)
                else:
                    input_db = self._evaluate_lookup(child[0], child[1], negated, input_db)
        else:
            # Grow database records over successive iterations
            #   Whatever is left at the end satisfy any criteria (OR)
            input_db = {}
            for child in criteria.children:
                if isinstance(child, Q):
                    results = self._filter(child, db)
                else:
                    results = self._evaluate_lookup(child[0], child[1], negated, db)

                input_db = {**input_db, **results}

        return input_db

    def _filter_objects(self, criteria: Q, page: int = 1, per_page: int = 10,
                        order_by: list = ()):
        """ Read the repository and return results as per the filer"""

        if criteria.children:
            items = list(self._filter(criteria, self.conn['data'][self.model_name]).values())
        else:
            items = list(self.conn['data'][self.model_name].values())

        # Sort the filtered results based on the order_by clause
        for o_key in order_by:
            reverse = False
            if o_key.startswith('-'):
                reverse = True
                o_key = o_key[1:]
            items = sorted(items, key=itemgetter(o_key), reverse=reverse)

        # Build the pagination results for the filtered items
        cur_offset, cur_limit = None, None
        if per_page > 0:
            cur_offset = (page - 1) * per_page
            cur_limit = page * per_page

        result = Pagination(
            page=page,
            per_page=per_page,
            total=len(items),
            items=items[cur_offset: cur_limit])
        return result

    def _update_object(self, model_obj):
        """ Update the entity record in the dictionary """
        identifier = model_obj[self.entity_cls.meta_.id_field.field_name]
        with self.conn['lock']:
            # Check if object is present
            if identifier not in self.conn['data'][self.model_name]:
                raise ObjectNotFoundError(
                    f'`{self.__class__.__name__}` object with identifier {identifier} '
                    f'does not exist.')

            self.conn['data'][self.model_name][identifier] = model_obj
        return model_obj

    def _update_all_objects(self, criteria: Q, *args, **kwargs):
        """ Update all objects satisfying the criteria """
        items = self._filter(criteria, self.conn['data'][self.model_name])

        update_count = 0
        for key in items:
            item = items[key]
            item.update(*args)
            item.update(kwargs)
            self.conn['data'][self.model_name][key] = item

            update_count += 1

        return update_count

    def _delete_object(self, model_obj):
        """ Delete the entity record in the dictionary """
        identifier = model_obj[self.entity_cls.meta_.id_field.field_name]
        with self.conn['lock']:
            # Check if object is present
            if identifier not in self.conn['data'][self.model_name]:
                raise ObjectNotFoundError(
                    f'`{self.__class__.__name__}` object with identifier {identifier} '
                    f'does not exist.')

            del self.conn['data'][self.model_name][identifier]
        return model_obj

    def _delete_all_objects(self, criteria: Q):
        """ Delete the dictionary object by its criteria"""

        # Delete the object from the dictionary and return the deletion count
        items = self._filter(criteria, self.conn['data'][self.model_name])

        # Delete all the matching identifiers
        for identifier in items:
            self.conn['data'][self.model_name].pop(identifier, None)

        return len(items)

    def delete_all(self):
        """ Delete all objects in this schema """
        with self.conn['lock']:
            if self.model_name in self.conn['data']:
                del self.conn['data'][self.model_name]


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
        if isinstance(self.source, str):
            return "'%s'" % self.source
        return self.source

    def process_target(self):
        """Return target with transformations, if any"""
        if isinstance(self.target, str):
            return "'%s'" % self.target
        return self.target

    def as_expression(self):
        return '%s %s %s' % (self.process_source(),
                             operators[self.lookup_name],
                             self.process_target())


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


class DictModel(BaseModel):
    """ A model for the dictionary repository"""

    @classmethod
    def from_entity(cls, entity):
        """ Convert the entity to a dictionary record """
        dict_obj = {}
        for field_name in entity.__class__.meta_.attributes:
            dict_obj[field_name] = getattr(entity, field_name)
        return dict_obj

    @classmethod
    def to_entity(cls, item):
        """ Convert the dictionary record to an entity """
        return cls.opts_.entity_cls(item)
