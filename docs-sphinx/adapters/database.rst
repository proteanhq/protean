Database Adapters
=================

Elasticsearch
-------------

To use Elasticsearch as a database provider, use the below configuration setting:

.. code-block:: python

    DATABASES = {
        "default": {
            "PROVIDER": "protean.adapters.repository.elasticsearch.ESProvider",
            "DATABASE": Database.ELASTICSEARCH.value,
            "DATABASE_URI": {"hosts": ["localhost"]},
            "NAMESPACE_PREFIX": os.environ.get("PROTEAN_ENV"),
            "SETTINGS": {"number_of_shards": 3}
        },
    }

Additional options are available for finer control:

.. py:data:: NAMESPACE_PREFIX

    Index names in Elasticsearch instance are prefixed with the specified string. For example, if the namespace
    prefix is "prod", the index of an aggregate `Person` will be `prod-person`.

.. py:data:: NAMESPACE_SEPARATOR

    Custom character to join NAMESPACE_PREFIX and index name. Default is hyphen (`-`). For example, with
    `NAMESPACE_SEPARATOR` as `_`, the index of aggregate `Person` will be `prod_person`.

.. py:data:: SETTINGS

    Index settings passed on to Elasticsearch instance.

Note that if you supply a custom Elasticsearch Model with an `Index` inner class, the options specified in the
inner class override those at the config level.

In the sample below, with the configuration settings specified above, the options at Aggregate level will be
overridden and the Elasticsearch Model will have the default index value `*` and number of shards as `1`.

.. code-block:: python

    class Person(BaseAggregate):
        name = String()
        about = Text()

        class Meta:
            schema_name = "people"

    class PeopleModel(ElasticsearchModel):
        name = Text(fields={"raw": Keyword()})
        about = Text()

        class Index:
            settings = {"number_of_shards": 1}
