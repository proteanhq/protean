""" Implementation of a dictionary based repository """

from collections import defaultdict
from itertools import count

from operator import itemgetter

from protean.core.field import Auto
from protean.core.repository import BaseRepository, BaseSchema, \
    Pagination, BaseConnectionHandler


class Repository(BaseRepository):
    """ A repository for storing data in a dictionary """

    def _set_auto_fields(self, schema_obj):
        """ Set the values of the auto field using counter"""
        for field_name, field_obj in \
                self.entity_cls.meta_.declared_fields.items():
            counter_key = f'{self.schema_name}_{field_name}'
            if isinstance(field_obj, Auto) and \
                    not getattr(schema_obj, field_name, None):

                # Increment the counter and it should start from 1
                counter = next(self.conn['counters'][counter_key])
                if not counter:
                    counter = next(self.conn['counters'][counter_key])
                schema_obj[field_name] = counter
        return schema_obj

    def _create_object(self, schema_obj):
        """ Write a record to the dict repository"""
        # Update the value of the counters
        schema_obj = self._set_auto_fields(schema_obj)

        # Add the entity to the repository
        identifier = schema_obj[self.entity_cls.meta_.id_field[0]]
        self.conn['data'][self.schema_name][identifier] = schema_obj
        return schema_obj

    def _filter_objects(self, page: int = 1, per_page: int = 10,
                        order_by: list = (), _excludes=None, **filters):
        """ Read the repository and return results as per the filer"""

        # Filter the dictionary objects based on the filters
        items = []
        excludes = _excludes if _excludes else {}
        for item in self.conn['data'][self.schema_name].values():
            match = True

            # Add objects that match the given filters
            for fk, fv in filters.items():
                if item[fk] != fv:
                    match = False

            # Add objects that do not match excludes
            for fk, fv in excludes.items():
                if item[fk] == fv:
                    match = False

            if match:
                items.append(item)

        # Sort the filtered results based on the order_by clause
        for o_key in order_by:
            reverse = False
            if o_key.startswith('-'):
                reverse = True
                o_key = o_key[1:]
            items = sorted(items, key=itemgetter(o_key), reverse=reverse)

        # Build the pagination results for the filtered items
        cur_offset = (page - 1) * per_page
        cur_limit = page * per_page
        result = Pagination(
            page=page,
            per_page=per_page,
            total=len(items),
            items=items[cur_offset: cur_limit])
        return result

    def _update_object(self, schema_obj):
        """ Update the entity record in the dictionary """
        identifier = schema_obj[self.entity_cls.meta_.id_field[0]]
        self.conn['data'][self.schema_name][identifier] = schema_obj
        return schema_obj

    def _delete_objects(self, **filters):
        """ Delete the dictionary object by its id"""

        # Delete the object from the dictionary and return the deletion count
        delete_ids = []
        for identifier, item in self.conn['data'][self.schema_name].items():
            match = True

            # Add objects that match the given filters
            for fk, fv in filters.items():
                if item[fk] != fv:
                    match = False
            if match:
                delete_ids.append(identifier)

        # Delete all the matching identifiers
        for identifier in delete_ids:
            del self.conn['data'][self.schema_name][identifier]

        return len(delete_ids)

    def delete_all(self):
        """ Delete all objects in this schema """
        del self.conn['data'][self.schema_name]


class DictSchema(BaseSchema):
    """ A schema for the dictionary repository"""

    @classmethod
    def from_entity(cls, entity):
        """ Convert the entity to a dictionary record """
        dict_obj = {}
        for field_name in entity.meta_.declared_fields:
            dict_obj[field_name] = getattr(entity, field_name)
        return dict_obj

    @classmethod
    def to_entity(cls, item):
        """ Convert the dictionary record to an entity """
        return cls.opts_.entity_cls(item)


class ConnectionHandler(BaseConnectionHandler):
    """ Handle connections to the dict repository """

    def __init__(self, conn_info):
        self.conn_info = conn_info

    def get_connection(self):
        """ Return the dictionary database object """
        return {'data': defaultdict(dict),
                'counters': defaultdict(count)}
