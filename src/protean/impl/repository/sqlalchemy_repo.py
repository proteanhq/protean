"""Module with repository implementation for SQLAlchemy
"""
# Standard Library Imports
from abc import ABCMeta
from typing import Any

# Protean
from protean.core import field
from protean.core.entity import BaseEntity
from protean.core.provider.base import BaseProvider
from protean.core.repository import BaseLookup, BaseModel, BaseRepository, ResultSet, repo_factory
from protean.utils.query import Q
from sqlalchemy import Column, MetaData, and_, create_engine, or_, orm
from sqlalchemy import types as sa_types
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext import declarative as sa_dec
from sqlalchemy.ext.declarative import as_declarative, declared_attr


class DeclarativeMeta(sa_dec.DeclarativeMeta, ABCMeta):
    """ Metaclass for the Sqlalchemy declarative schema """
    field_mapping = {
        field.Auto: sa_types.Integer,
        field.String: sa_types.String,
        field.Text: sa_types.Text,
        field.Boolean: sa_types.Boolean,
        field.Integer: sa_types.Integer,
        field.Float: sa_types.Float,
        field.List: sa_types.PickleType,
        field.Dict: sa_types.PickleType,
        field.Date: sa_types.Date,
        field.DateTime: sa_types.DateTime,
    }

    def __init__(cls, classname, bases, dict_):
        # Update the class attrs with the entity attributes
        if hasattr(cls, 'entity_cls'):
            entity_cls = cls.entity_cls
            for field_name, field_obj in entity_cls.meta_.declared_fields.items():

                # Map the field if not in attributes
                if field_name not in cls.__dict__:
                    field_cls = type(field_obj)
                    if field_cls == field.Reference:
                        related_ent = repo_factory.get_entity(field_obj.to_cls.__name__)
                        if field_obj.via:
                            related_attr = getattr(
                                related_ent, field_obj.via)
                        else:
                            related_attr = related_ent.meta_.id_field
                        field_name = field_obj.get_attribute_name()
                        field_cls = type(related_attr)

                    # Get the SA type and default to the text type if no
                    # mapping is found
                    sa_type_cls = cls.field_mapping.get(field_cls)
                    if not sa_type_cls:
                        sa_type_cls = sa_types.String

                    # Build the column arguments
                    col_args = {
                        'primary_key': field_obj.identifier,
                        'nullable': not field_obj.required,
                        'unique': field_obj.unique
                    }

                    # Update the arguments based on the field type
                    type_args = {}
                    if issubclass(field_cls, field.String):
                        type_args['length'] = field_obj.max_length

                    # Update the attributes of the class
                    setattr(cls, field_name,
                            Column(sa_type_cls(**type_args), **col_args))
        super().__init__(classname, bases, dict_)


@as_declarative(metaclass=DeclarativeMeta)
class SqlalchemyModel(BaseModel):
    """Model representation for the Sqlalchemy Database """

    @declared_attr
    def __tablename__(cls):
        return cls.entity_cls.meta_.schema_name

    @classmethod
    def from_entity(cls, entity: BaseEntity):
        """ Convert the entity to a model object """
        item_dict = {}
        for field_obj in cls.entity_cls.meta_.attributes.values():
            if isinstance(field_obj, field.Reference):
                item_dict[field_obj.relation.field_name] = \
                    field_obj.relation.value
            else:
                item_dict[field_obj.field_name] = getattr(
                    entity, field_obj.field_name)
        return cls(**item_dict)

    @classmethod
    def to_entity(cls, model_obj: 'SqlalchemyModel'):
        """ Convert the model object to an entity """
        item_dict = {}
        for field_name in cls.entity_cls.meta_.attributes:
            item_dict[field_name] = getattr(model_obj, field_name, None)
        return cls.entity_cls(item_dict)


class SARepository(BaseRepository):
    """Repository implementation for Databases compliant with SQLAlchemy"""

    def _build_filters(self, criteria: Q):
        """ Recursively Build the filters from the criteria object"""
        # Decide the function based on the connector type
        func = and_ if criteria.connector == criteria.AND else or_
        params = []
        for child in criteria.children:
            if isinstance(child, Q):
                # Call the function again with the child
                params.append(self._build_filters(child))
            else:
                # Find the lookup class and the key
                stripped_key, lookup_class = self.provider._extract_lookup(child[0])

                # Instantiate the lookup class and get the expression
                lookup = lookup_class(stripped_key, child[1], self.model_cls)
                if criteria.negated:
                    params.append(~lookup.as_expression())
                else:
                    params.append(lookup.as_expression())

        return func(*params)

    def filter(self, criteria: Q, offset: int = 0, limit: int = 10,
               order_by: list = ()) -> ResultSet:
        """ Filter objects from the sqlalchemy database """
        qs = self.conn.query(self.model_cls)

        # Build the filters from the criteria
        if criteria.children:
            qs = qs.filter(self._build_filters(criteria))

        # Apply the order by clause if present
        order_cols = []
        for order_col in order_by:
            col = getattr(self.model_cls, order_col.lstrip('-'))
            if order_col.startswith('-'):
                order_cols.append(col.desc())
            else:
                order_cols.append(col)
        qs = qs.order_by(*order_cols)
        qs = qs.limit(limit).offset(offset)

        # Return the results
        try:
            items = qs.all()
            result = ResultSet(
                offset=offset,
                limit=limit,
                total=qs.count(),
                items=items[offset: offset + limit])
        except DatabaseError:
            self.conn.rollback()
            raise

        return result

    def create(self, model_obj):
        """ Add a new record to the sqlalchemy database"""
        self.conn.add(model_obj)

        try:
            # If the model has Auto fields then flush to get them
            if self.entity_cls.meta_.auto_fields:
                self.conn.flush()
            self.conn.commit()
        except DatabaseError:
            self.conn.rollback()
            raise

        return model_obj

    def update(self, model_obj):
        """ Update a record in the sqlalchemy database"""
        primary_key, data = {}, {}
        for field_name, field_obj in \
                self.entity_cls.meta_.declared_fields.items():
            if field_obj.identifier:
                primary_key = {
                    field_name: getattr(model_obj, field_name)
                }
            else:
                if isinstance(field_obj, field.Reference):
                    data[field_obj.relation.field_name] = \
                        field_obj.relation.value
                else:
                    data[field_name] = getattr(model_obj, field_name, None)

        # Run the update query and commit the results
        try:
            self.conn.query(self.model_cls).filter_by(
                **primary_key).update(data)
            self.conn.commit()
        except DatabaseError:
            self.conn.rollback()
            raise

        return model_obj

    def update_all(self, criteria: Q, *args, **kwargs):
        """ Update all objects satisfying the criteria """
        # Delete the objects and commit the results
        qs = self.conn.query(self.model_cls).filter(self._build_filters(criteria))
        try:
            values = args or {}
            values.update(kwargs)
            updated_count = qs.update(values)
            self.conn.commit()
        except DatabaseError:
            self.conn.rollback()
            raise
        return updated_count

    def delete(self, model_obj):
        """ Delete the entity record in the dictionary """
        identifier = getattr(model_obj, self.entity_cls.meta_.id_field.field_name)
        primary_key = {self.entity_cls.meta_.id_field.field_name: identifier}
        try:
            self.conn.query(self.model_cls).filter_by(**primary_key).delete()
            self.conn.commit()
        except DatabaseError:
            self.conn.rollback()
            raise

        return model_obj

    def delete_all(self, criteria: Q = None):
        """ Delete a record from the sqlalchemy database"""
        del_count = 0
        if criteria:
            qs = self.conn.query(self.model_cls).filter(self._build_filters(criteria))
        else:
            qs = self.conn.query(self.model_cls)

        try:
            del_count = qs.delete()
            self.conn.commit()
        except DatabaseError:
            self.conn.rollback()
            raise

        return del_count

    def raw(self, query: Any, data: Any = None):
        """Run a raw query on the repository and return entity objects"""
        assert isinstance(query, str)

        try:
            results = self.conn.execute(query)

            entity_items = []
            for item in results:
                entity = self.model_cls.to_entity(item)
                entity.state_.mark_retrieved()
                entity_items.append(entity)

            result = ResultSet(
                offset=0,
                limit=len(entity_items),
                total=len(entity_items),
                items=entity_items)
        except DatabaseError:
            self.conn.rollback()
            raise

        return result


class SAProvider(BaseProvider):
    """Provider Implementation class for SQLAlchemy"""

    def __init__(self, *args, **kwargs):
        """Initialize and maintain Engine"""
        super().__init__(*args, **kwargs)

        self._engine = create_engine(make_url(self.conn_info['DATABASE_URI']))
        self._metadata = MetaData(bind=self._engine)

        self._model_classes = {}

    def get_session(self):
        """Establish a session to the Database"""
        # Create the session
        session_factory = orm.sessionmaker(bind=self._engine)
        session_cls = orm.scoped_session(session_factory)

        return session_cls

    def get_connection(self, session_cls=None):
        """ Create the connection to the Database instance"""
        # If this connection has to be created within an existing session,
        #   ``session_cls`` will be provided as an argument.
        #   Otherwise, fetch a new ``session_cls`` from ``get_session()``
        if session_cls is None:
            session_cls = self.get_session()

        return session_cls()

    def close_connection(self, conn):
        """ Close the connection to the Database instance """
        conn.close()

    def get_model(self, entity_cls):
        """Return a fully-baked Model class for a given Entity class"""
        model_cls = None

        if entity_cls.meta_.schema_name in self._model_classes:
            model_cls = self._model_classes[entity_cls.meta_.schema_name]
        else:
            attrs = {
                'entity_cls': entity_cls,
                'metadata': self._metadata
            }
            model_cls = type(entity_cls.__name__ + 'Model', (SqlalchemyModel, ), attrs)

            self._model_classes[entity_cls.meta_.schema_name] = model_cls

        # Set Entity Class as a class level attribute for the Model, to be able to reference later.
        return model_cls

    def get_repository(self, entity_cls):
        """ Return a repository object configured with a live connection"""
        return SARepository(self, entity_cls, self.get_model(entity_cls))

    def raw(self, query: Any, data: Any = None):
        """Run raw query on Provider"""
        if data is None:
            data = {}
        assert isinstance(query, str)
        assert isinstance(data, (dict, None))

        return self.get_connection().execute(query, data)


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


class DefaultLookup(BaseLookup):
    """Base class with default implementation of expression construction"""

    def __init__(self, source, target, model_cls):
        """Source is LHS and Target is RHS of a comparsion"""
        self.model_cls = model_cls
        super().__init__(source, target)

    def process_source(self):
        """Return source with transformations, if any"""
        source_col = getattr(self.model_cls, self.source)
        return source_col

    def process_target(self):
        """Return target with transformations, if any"""
        return self.target

    def as_expression(self):
        lookup_func = getattr(self.process_source(),
                              operators[self.lookup_name])
        return lookup_func(self.process_target())


@SAProvider.register_lookup
class Exact(DefaultLookup):
    """Exact Match Query"""
    lookup_name = 'exact'


@SAProvider.register_lookup
class IExact(DefaultLookup):
    """Exact Case-Insensitive Match Query"""
    lookup_name = 'iexact'


@SAProvider.register_lookup
class Contains(DefaultLookup):
    """Exact Contains Query"""
    lookup_name = 'contains'


@SAProvider.register_lookup
class IContains(DefaultLookup):
    """Exact Case-Insensitive Contains Query"""
    lookup_name = 'icontains'

    def process_target(self):
        """Return target in lowercase"""
        assert isinstance(self.target, str)
        return f"%{super().process_target()}%"


@SAProvider.register_lookup
class Startswith(DefaultLookup):
    """Exact Contains Query"""
    lookup_name = 'startswith'


@SAProvider.register_lookup
class Endswith(DefaultLookup):
    """Exact Contains Query"""
    lookup_name = 'endswith'


@SAProvider.register_lookup
class GreaterThan(DefaultLookup):
    """Greater than Query"""
    lookup_name = 'gt'


@SAProvider.register_lookup
class GreaterThanOrEqual(DefaultLookup):
    """Greater than or Equal Query"""
    lookup_name = 'gte'


@SAProvider.register_lookup
class LessThan(DefaultLookup):
    """Less than Query"""
    lookup_name = 'lt'


@SAProvider.register_lookup
class LessThanOrEqual(DefaultLookup):
    """Less than or Equal Query"""
    lookup_name = 'lte'


@SAProvider.register_lookup
class In(DefaultLookup):
    """In Query"""
    lookup_name = 'in'

    def process_target(self):
        """Ensure target is a list or tuple"""
        assert isinstance(self.target, (list, tuple))
        return super().process_target()


@SAProvider.register_lookup
class Overlap(DefaultLookup):
    """In Query"""
    lookup_name = 'in'

    def process_target(self):
        """Ensure target is a list or tuple"""
        assert isinstance(self.target, (list, tuple))
        return super().process_target()


@SAProvider.register_lookup
class Any(DefaultLookup):
    """In Query"""
    lookup_name = 'in'

    def process_target(self):
        """Ensure target is a list or tuple"""
        assert isinstance(self.target, (list, tuple))
        return super().process_target()
