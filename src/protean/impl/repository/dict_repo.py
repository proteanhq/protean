""" Implementation of a dictionary based repository """

from collections import defaultdict

from operator import itemgetter

from protean.core.entity import Entity
from protean.core.exceptions import DuplicateObjectError
from protean.core.repository import BaseRepository, BaseRepositorySchema, \
    Pagination, BaseConnectionHandler


class Repository(BaseRepository):
    """ A repository for storing data in a dictionary """
    def _create_object(self, entity: Entity):
        """ Write a record to the dict repository"""

        # Check if the entity already exists in the repo
        identifier = getattr(entity, entity.id_field[0])
        if identifier in self.conn[self.schema.name]:
            raise DuplicateObjectError(
                f'Entity with id {identifier} already exists')

        # Add the entity to the repository
        self.conn[self.schema.name][identifier] = \
            self.schema.from_entity(entity)
        return entity

    def _filter_objects(self, page: int = 1, per_page: int = 10,
                        order_by: list = (), **filters):
        """ Read the repository and return results as per the filer"""

        # Filter the dictionary objects based on the filters
        items = []
        for item in self.conn[self.schema.name].values():
            for fk, fv in filters.items():
                if item[fk] != fv:
                    break
            else:
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

    def _update_object(self, entity: Entity):
        """ Update the entity record in the dictionary """
        identifier = getattr(entity, entity.id_field[0])
        self.conn[self.schema.name][identifier] = self.schema.from_entity(
            entity)
        return entity

    def delete(self, identifier):
        """ Delete the dictionary object by its id"""

        # Delete the object from the dictionary and return the deletion count
        del_count = 0
        try:
            del self.conn[self.schema.name][identifier]
            del_count += 1
        except KeyError:
            pass
        return del_count


class RepositorySchema(BaseRepositorySchema):
    """ A schema for the dictionary repository"""

    def from_entity(self, entity):
        """ Convert the entity to a dictionary record """
        dict_obj = {}
        for field_name in entity.declared_fields:
            dict_obj[field_name] = getattr(entity, field_name)
        return dict_obj

    def to_entity(self, item):
        """ Convert the dictionary record to an entity """
        return self.opts.entity_cls(item)


class ConnectionHandler(BaseConnectionHandler):
    """ Handle connections to the dict repository """

    def __init__(self, conn_info):
        self.conn_info = conn_info

    def get_connection(self):
        """ Return the dictionary database object """
        return defaultdict(dict)
