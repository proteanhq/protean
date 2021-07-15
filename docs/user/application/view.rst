=====
Views
=====

Views are read-only data representations on the **read** side of the CQRS pattern, that cater to specific requirements typically outlined by APIs or Reports. They are also referred to as Projections (especially in EventSourcing) or Read-only Models.

Views look and feel very similar to :ref:`Entities <entity>` with a couple of important exceptions:

* **A View's identity is never auto-generated**: While an identity field called `id` is still added automatically to the view model, it is up to the domain to generate and assign identifiers. The unique identifier for the view - either a primary key of an existing data record or dynamically generated - should be populated explicitly.
* **A View can only contain basic types of fields**: Other Domain Elements like Value Objects, as well as relationships like Reference, HasOne, and HasMany are not permitted. This is to encourage developers to construct views as wholesome data records, that don't contain complex business rules and don't require combining data from different views.

Defining a View
---------------

A view is defined with `@domain.view` decorator:

.. code-block:: python

    @domain.view
    class ArticleRatingsCount:
        article_id = Identifier(identifier=True)
        rating = Integer(min_value=1, max_value=1)
        count = Integer(min_value=0, default=0)

Note the explicitly defined :ref:`Identifier <api-field-basic-identifier>` `article_id`.

The `Identifier` field can be explicitly marked `Auto` conveying to Protean that the identity of the View is auto-generated.

View Identifiers
----------------

When an identifier field is not specified explicitly, Protean adds a field named ``id`` of ``Identifier`` type:

.. code-block:: python

    @domain.view
    class ArticleRatingsCount:
        article_id = Identifier()
        rating = Integer(min_value=1, max_value=1)
        count = Integer(min_value=0, default=0)

.. code-block:: python

    > print(ArticleRatingsCount.meta_.attribute)
    {'article_id': <protean.core.field.basic.Identifier at ...>,
    'rating': <protean.core.field.basic.Integer at ...>,
    'count': <protean.core.field.basic.Integer at ...>,
    'id': <protean.core.field.basic.Identifier at ...>}

Note that unlike in Aggregates or Entities, the ``id`` field is **not** an :ref:`api-field-basic-auto` field. It is a standard :ref:`api-field-basic-identifier`.

You can specify an explicit identifier field to a view:

.. code-block:: python

    class PersonExplicitID(BaseView):
        ssn = String(max_length=36, identifier=True)
        first_name = String(max_length=50, required=True)
        last_name = String(max_length=50)
        age = Integer(default=21)

You can also make the explicit identifier generate identities automatically:

.. code-block:: python

    class PersonAutoSSN(BaseView):
        ssn = Auto(identifier=True)
        first_name = String(max_length=50, required=True)
        last_name = String(max_length=50)
        age = Integer(default=21)

Populating a View
-----------------

Views are typically populated and maintained by Event Handlers:

.. code-block:: python

    @domain.event
    class ArticleRated:
        article_id = Identifier(identifier=True)
        rated_by = Identifier()
        rating = Integer(min_value=1, max_value=1)

    @domain.subscriber(event=ArticleRated)
    class PopulateArticleRatingsCount:
        def notify(self, event):
            repo = current_domain.repository_for(ArticleRatingsCount)

            rating_record = repo.find_by_article(event['article_id'])
            rating_record.count += 1
            repo.add(rating_record)

You can fetch repositories associated with a View to load and persist data, similar to aggregates. But remember that Aggregates are the wholesome object clusters that work on the "write" side of the domain and protect the domain, while Views are read-only data objects that can be discarded and rebuilt from scratch, if required.

View Options
------------

Views accept all options supported by Entities:

* ``abstract``: Mark if the View definition is abstract. Defaulted to ``False``.
* ``schema_name``: Override the underlying structure (table, document, key, etc.) name. Defaulted to the snake case version of view name.
* ``provider``: The database or cache provider name
* ``model``: Custom :ref:`Model <model>` associated with the View.

Storing Views in Cache
----------------------

If the view is a temporary data structure, it can be directly stored as part of a Cache.

.. code-block:: python

    @domain.view
    class ArticleRatingsCount:
        article_id = Identifier()
        rating = Integer(min_value=1, max_value=1)
        count = Integer(min_value=0, default=0)

        class Meta:
            cache = True
            provider = "default"

.. note:: Views can optionally use cache as the storage mechanism, but it is important to remember that Protean caches only work with views. Caches cannot be used to persist other types of domain elements like Aggregates and Entities.
