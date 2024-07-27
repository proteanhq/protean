"""Implementation of a dictionary based repository"""

import copy
import json
from collections import defaultdict
from datetime import date, datetime
from itertools import count
from operator import itemgetter
from threading import Lock
from typing import Any
from uuid import UUID

from protean.core.model import BaseModel
from protean.core.queryset import ResultSet
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields.basic import Auto
from protean.port.dao import BaseDAO, BaseLookup
from protean.port.provider import BaseProvider
from protean.utils.container import Options
from protean.utils.globals import current_uow
from protean.utils.query import Q
from protean.utils.reflection import attributes, fields, id_field


def derive_schema_name(model_cls):
    if hasattr(model_cls.meta_, "schema_name"):
        return model_cls.meta_.schema_name
    else:
        return model_cls.meta_.part_of.meta_.schema_name


class MemoryModel(BaseModel):
    """A model for the dictionary repository"""

    @classmethod
    def from_entity(cls, entity) -> "MemoryModel":
        """Convert the entity to a dictionary record"""
        dict_obj = {}
        for attribute_name in attributes(entity):
            dict_obj[attribute_name] = getattr(entity, attribute_name)
        return dict_obj

    @classmethod
    def to_entity(cls, item: "MemoryModel"):
        """Convert the dictionary record to an entity"""
        return cls.meta_.part_of(**item)


class MemorySession:
    def __init__(self, provider, new_connection=False):
        self._provider = provider
        self.is_active = True

        if (
            current_uow and self._provider.name in current_uow._sessions
        ) and not new_connection:
            self._db = current_uow._sessions[self._provider.name]._db
        else:
            self._db = {
                "data": copy.deepcopy(self._provider._databases),
                "lock": self._provider._locks.setdefault(self._provider.name, Lock()),
                "counters": self._provider._counters,
            }

    def add(self, element):
        if element.state_.is_persisted:
            dao = self._provider.get_dao(element.__class__)
            dao.update(element, element.to_dict())
        else:
            dao = self._provider.get_dao(element.__class__)
            dao.create(element.to_dict())

    def delete(self, element):
        dao = self._provider.get_dao(element.__class__)
        dao.delete(element)

    def commit(self):
        if current_uow and self._provider.name in current_uow._sessions:
            current_uow._sessions[self._provider.name]._db["data"] = self._db["data"]
        else:
            self._provider._databases = self._db["data"]

    def rollback(self):
        pass

    def close(self):
        pass


class MemoryProvider(BaseProvider):
    """Provider class for Dict Repositories"""

    __database__ = "memory"

    def __init__(self, name, domain, conn_info: dict):
        """Initialize Provider with Connection/Adapter details"""

        # In case of `MemoryProvider`, the `database` value will always be `memory`.
        super().__init__(name, domain, conn_info)

        # Global in-memory store of dict data.
        self._databases = defaultdict(dict)
        self._locks = defaultdict(Lock)
        self._counters = defaultdict(count)

        # A temporary cache of already constructed model classes
        self._model_classes = {}

    def get_session(self):
        """Return a session object

        For Dictionary Repo, a session translates to a copy of the
        `database`. All transactions on the Provider's repositories
        are committed on this copy of the database.
        """
        return MemorySession(self)

    def get_connection(self, session_cls=None):
        """Return the dictionary database object"""
        return MemorySession(self, new_connection=True)

    def is_alive(self) -> bool:
        """Check if the connection is alive"""
        return True

    def _data_reset(self):
        """Reset data"""
        self._databases = defaultdict(dict)
        self._locks = defaultdict(Lock)
        self._counters = defaultdict(count)

        # Discard any active Unit of Work
        if current_uow and current_uow.in_progress:
            current_uow.rollback()

    def decorate_model_class(self, entity_cls, model_cls):
        schema_name = derive_schema_name(model_cls)

        # Return the model class if it was already seen/decorated
        if schema_name in self._model_classes:
            return self._model_classes[schema_name]

        # If `model_cls` is already subclassed from MemoryModel,
        #   this method call is a no-op
        if issubclass(model_cls, MemoryModel):
            return model_cls
        else:
            custom_attrs = {
                key: value
                for (key, value) in vars(model_cls).items()
                if key not in ["Meta", "__module__", "__doc__", "__weakref__"]
            }

            meta_ = Options()
            meta_.part_of = entity_cls

            custom_attrs.update({"meta_": meta_})
            # FIXME Ensure the custom model attributes are constructed properly
            decorated_model_cls = type(
                model_cls.__name__, (MemoryModel, model_cls), custom_attrs
            )

            # Memoize the constructed model class
            self._model_classes[schema_name] = decorated_model_cls

            return decorated_model_cls

    def construct_model_class(self, entity_cls):
        """Return associated, fully-baked Model class"""
        model_cls = None

        # Return the model class if it was already seen/decorated
        if entity_cls.meta_.schema_name in self._model_classes:
            model_cls = self._model_classes[entity_cls.meta_.schema_name]
        else:
            meta_ = Options()
            meta_.part_of = entity_cls

            attrs = {
                "meta_": meta_,
            }
            # FIXME Ensure the custom model attributes are constructed properly
            model_cls = type(entity_cls.__name__ + "Model", (MemoryModel,), attrs)

            # Memoize the constructed model class
            self._model_classes[entity_cls.meta_.schema_name] = model_cls

        # Set Entity Class as a class level attribute for the Model, to be able to reference later.
        return model_cls

    def get_dao(self, entity_cls, model_cls):
        """Return a DAO object configured with a live connection"""
        return DictDAO(self.domain, self, entity_cls, model_cls)

    def _evaluate_lookup(self, key, value, negated, db):
        """Extract values from DB that match the given criteria"""
        results = {}
        for record_key, record_value in db.items():
            match = True

            stripped_key, lookup_class = self._extract_lookup(key)
            lookup = lookup_class(record_value[stripped_key], value)

            if record_value[stripped_key] is not None:
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

        for schema_name in conn._db["data"]:
            input_db = conn._db["data"][schema_name]
            try:
                # Ensures that the string contains double quotes around keys and values
                query = query.replace("'", '"')
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

    def _create_database_artifacts(self):
        """Dummy placeholder. Nothing to do."""

    def _drop_database_artifacts(self):
        """Dummy placeholder. Nothing to do."""


class DictDAO(BaseDAO):
    """A repository for storing data in a dictionary"""

    def __repr__(self) -> str:
        return f"DictDAO <{self.entity_cls.__name__}>"

    def _set_auto_fields(self, model_obj):
        """Set the values of the auto field using counter"""
        conn = self._get_session()

        for field_name, field_obj in fields(self.entity_cls).items():
            if type(field_obj) is Auto and field_obj.increment:
                counter_key = f"{self.schema_name}_{field_name}"
                if not (field_name in model_obj and model_obj[field_name] is not None):
                    # Increment the counter and it should start from 1
                    counter = next(conn._db["counters"][counter_key])
                    if not counter:
                        counter = next(conn._db["counters"][counter_key])

                    model_obj[field_name] = counter

        return model_obj

    def _create(self, model_obj):
        """Write a record to the dict repository"""
        conn = self._get_session()

        # Update the value of the counters
        model_obj = self._set_auto_fields(model_obj)

        # Add the entity to the repository
        identifier = model_obj[id_field(self.entity_cls).field_name]
        with conn._db["lock"]:
            # Check if object is present
            if identifier in conn._db["data"][self.schema_name]:
                raise ValidationError(
                    {
                        "_entity": f"`{self.__class__.__name__}` object with identifier {identifier} "
                        f"is already present."
                    }
                )

            conn._db["data"][self.schema_name][identifier] = model_obj

        if not current_uow:
            conn.commit()
            conn.close()

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
                    input_db = self.provider._evaluate_lookup(
                        child[0], child[1], negated, input_db
                    )
        else:
            # Grow database records over successive iterations
            #   Whatever is left at the end satisfy any criteria (OR)
            input_db = {}
            for child in criteria.children:
                if isinstance(child, Q):
                    results = self._filter_items(child, db)
                else:
                    results = self.provider._evaluate_lookup(
                        child[0], child[1], negated, db
                    )

                input_db = {**input_db, **results}

        return input_db

    def _filter(
        self, criteria: Q, offset: int = 0, limit: int = 10, order_by: list = ()
    ):
        """Read the repository and return results as per the filer"""
        conn = self._get_session()

        if criteria.children:
            items = list(
                self._filter_items(
                    criteria, conn._db["data"][self.schema_name]
                ).values()
            )
        else:
            items = list(conn._db["data"][self.schema_name].values())

        # Sort the filtered results based on the order_by clause
        for o_key in order_by:
            reverse = False
            if o_key.startswith("-"):
                reverse = True
                o_key = o_key[1:]

            null_items = [item for item in items if item.get(o_key) is None]
            non_null_items = [item for item in items if item.get(o_key) is not None]
            sorted_items = sorted(
                non_null_items, key=itemgetter(o_key), reverse=reverse
            )

            # null values sort as if larger than any non-null value
            # So in reverse (DESC) order, null values come first
            # in ASC order, null values come last
            if reverse:
                items = null_items + sorted_items
            else:
                items = sorted_items + null_items

        result = ResultSet(
            offset=offset,
            limit=limit,
            total=len(items),
            items=items[offset : offset + limit],
        )

        return result

    def _update(self, model_obj):
        """Update the entity record in the dictionary"""
        conn = self._get_session()

        identifier = model_obj[id_field(self.entity_cls).field_name]
        with conn._db["lock"]:
            # Check if object is present
            if identifier not in conn._db["data"][self.schema_name]:
                raise ObjectNotFoundError(
                    f"`{self.__class__.__name__}` object with identifier {identifier} "
                    f"does not exist."
                )

            conn._db["data"][self.schema_name][identifier] = model_obj

        if not current_uow:
            conn.commit()
            conn.close()

        return model_obj

    def _update_all(self, criteria: Q, *args, **kwargs):
        """Update all objects satisfying the criteria"""
        conn = self._get_session()

        items = self._filter_items(criteria, conn._db["data"][self.schema_name])

        update_count = 0
        for key in items:
            item = items[key]
            item.update(*args)
            item.update(kwargs)
            conn._db["data"][self.schema_name][key] = item

            update_count += 1

        if not current_uow:
            conn.commit()
            conn.close()

        return update_count

    def _delete(self, model_obj):
        """Delete the entity record in the dictionary"""
        conn = self._get_session()

        identifier = model_obj[id_field(self.entity_cls).field_name]
        with conn._db["lock"]:
            # Check if object is present
            if identifier not in conn._db["data"][self.schema_name]:
                raise ObjectNotFoundError(
                    f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                    f"does not exist."
                )

            del conn._db["data"][self.schema_name][identifier]

        if not current_uow:
            conn.commit()
            conn.close()

        return model_obj

    def _delete_all(self, criteria: Q = None):
        """Delete the dictionary object by its criteria"""
        conn = self._get_session()
        items = []

        if criteria:
            # Delete the object from the dictionary and return the deletion count
            items = self._filter_items(criteria, conn._db["data"][self.schema_name])

            # Delete all the matching identifiers
            with conn._db["lock"]:
                for identifier in items:
                    conn._db["data"][self.schema_name].pop(identifier, None)
        else:
            with conn._db["lock"]:
                if self.schema_name in conn._db["data"]:
                    del conn._db["data"][self.schema_name]

        if not current_uow:
            conn.commit()
            conn.close()

        return len(items)

    def _raw(self, query: Any, data: Any = None):
        """Run raw query on Repository.

        For this stand-in repository, the query string is a json string that contains kwargs
        criteria with straight-forward equality checks. Individual criteria are always AND-ed
        and the result is always a subset of the full repository.

        We will ignore the `data` parameter for this kind of repository.
        """
        # Ensure that we are dealing with a string, for this repository
        assert isinstance(query, str)

        conn = self._get_session()
        input_db = conn._db["data"][self.schema_name]
        result = None

        try:
            # Ensures that the string contains double quotes around keys and values
            query = query.replace("'", '"')
            criteria = json.loads(query)

            for key, value in criteria.items():
                input_db = self.provider._evaluate_lookup(key, value, False, input_db)

            items = list(input_db.values())
            result = ResultSet(
                offset=1, limit=len(items), total=len(items), items=items
            )

        except json.JSONDecodeError:
            # FIXME Log Exception
            raise Exception("Query Malformed")

        if not current_uow:
            conn.commit()
            conn.close()

        return result


operators = {
    "exact": "==",
    "iexact": "==",
    "contains": "in",
    "icontains": "in",
    "gt": ">",
    "gte": ">= ",
    "lt": "<",
    "lte": "<=",
    "in": "in",
    "any": "any",
}


class MemoryLookup(BaseLookup):
    """Base class with default implementation of expression construction"""

    def process_source(self):
        """Return source with transformations, if any"""
        if isinstance(self.source, (UUID, datetime, date)):
            self.source = str(self.source)

        if isinstance(self.source, str):
            # Replace single and double quotes with escaped single-quote
            self.source = self.source.replace("'", "'").replace('"', "'")
            return '"{source}"'.format(source=self.source)
        return self.source

    def process_target(self):
        """Return target with transformations, if any"""
        if isinstance(self.target, (UUID, datetime, date)):
            self.target = str(self.target)

        if isinstance(self.target, str):
            # Replace single and double quotes with escaped single-quote
            self.target = self.target.replace("'", "'").replace('"', "'")
            return '"{target}"'.format(target=self.target)
        return self.target

    def as_expression(self):
        return "{source} {op} {target}".format(
            source=self.process_source(),
            op=operators[self.lookup_name],
            target=self.process_target(),
        )


@MemoryProvider.register_lookup
class Exact(MemoryLookup):
    """Exact Match Query"""

    lookup_name = "exact"


@MemoryProvider.register_lookup
class IExact(MemoryLookup):
    """Exact Case-Insensitive Match Query"""

    lookup_name = "iexact"

    def process_source(self):
        """Return source in lowercase"""
        assert isinstance(self.source, str)
        return "%s.lower()" % super().process_source()

    def process_target(self):
        """Return target in lowercase"""
        assert isinstance(self.target, str)
        return "%s.lower()" % super().process_target()


@MemoryProvider.register_lookup
class Contains(MemoryLookup):
    """Exact Contains Query"""

    lookup_name = "contains"

    def as_expression(self):
        """Check for Target string to be in Source string"""
        return "%s %s %s" % (
            self.process_target(),
            operators[self.lookup_name],
            self.process_source(),
        )


@MemoryProvider.register_lookup
class IContains(MemoryLookup):
    """Exact Case-Insensitive Contains Query"""

    lookup_name = "icontains"

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
        return "%s %s %s" % (
            self.process_target(),
            operators[self.lookup_name],
            self.process_source(),
        )


@MemoryProvider.register_lookup
class GreaterThan(MemoryLookup):
    """Greater than Query"""

    lookup_name = "gt"


@MemoryProvider.register_lookup
class GreaterThanOrEqual(MemoryLookup):
    """Greater than or Equal Query"""

    lookup_name = "gte"


@MemoryProvider.register_lookup
class LessThan(MemoryLookup):
    """Less than Query"""

    lookup_name = "lt"


@MemoryProvider.register_lookup
class LessThanOrEqual(MemoryLookup):
    """Less than or Equal Query"""

    lookup_name = "lte"


@MemoryProvider.register_lookup
class In(MemoryLookup):
    """In Query"""

    lookup_name = "in"

    def process_target(self):
        """Ensure target is a list or tuple"""
        target = super().process_target()
        return f"[{target}]" if not isinstance(target, list) else target


@MemoryProvider.register_lookup
class Any(MemoryLookup):
    """Any Query for Lists"""

    lookup_name = "any"

    def process_source(self):
        """Ensure source is a list"""
        source = super().process_source()
        return f"[{source}]" if not isinstance(source, list) else source

    def process_target(self):
        """Ensure target is a list"""
        target = super().process_target()
        return f"[{target}]" if not isinstance(target, list) else target

    def as_expression(self):
        return f"any(x in {self.process_target()} for x in {self.process_source()})"
