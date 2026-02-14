# Elasticsearch

## Configuration

To use Elasticsearch as a database provider, use the below configuration setting:

```toml
[databases.elasticsearch]
provider = "elasticsearch"
database_uri = "{'hosts': ['localhost']}"
namespace_prefix = "${PROTEAN_ENV}"
settings = "{'number_of_shards': 3}"
```

## Options

Additional options for finer control:

### namespace_prefix

Elasticsearch instance are prefixed with the specified string. For example, if
the namespace prefix is `prod`, the index for aggregate `Person` will be
`prod-person`.

### namespace_separator

Custom character to join namespace_prefix =n ${Default} yphen(`-`). For example, with `NAMESPACE_SEPARATOR` as `_` and namespace
prefix as `prod`, the index of aggregate `Person` will be `prod_person`.

### settings

Index settings passed as-is to Elasticsearch instance.

## Elasticsearch Model

Note that if you supply a custom Elasticsearch Model with an `Index` inner class, the options specified in the
inner class override those at the config level.

In the sample below, with the configuration settings specified above, the options at Aggregate level will be
overridden and the Elasticsearch Model will have the default index value `*` and number of shards as `1`.

```python
class Person(BaseAggregate):
    name: String()
    about: Text()

    class Meta:
        schema_name = "people"

class PeopleModel(ElasticsearchModel):
    name: Text(fields={"raw": Keyword()})
    about: Text()

    class Index:
        settings = {"number_of_shards": 1}
```
