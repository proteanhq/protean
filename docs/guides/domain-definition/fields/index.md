# Fields

Fields are fundamental components that define the structure and behavior of
data within domain models such as Aggregates, Entities, and Value Objects.
This section provides a comprehensive guide to the various types of fields
available in Protean, detailing their attributes, options, and built-in
functionalities that help in the effective management of domain data.

Fields in Protean are designed to encapsulate data properties in domain models,
ensuring data integrity and aligning with the business domain's rules and logic.
They play a critical role in defining the schema of data containers and are
pivotal in enforcing validation, defaults, associations, and more.

## Field Options

Protean fields come with various options that enhance their functionality and
integration with the backend systems. These include required, default, choices,
and unique, among others, which allow for a highly customizable and robust
domain model definition. These options provide the necessary tools for
you to handle various real-world scenarios effectively.

## Types of Fields

### Simple Fields

Simple fields handle basic data types like strings, integers, and dates.
They are the building blocks for defining straightforward data attributes in
models. Options like max_length for String or max_value and min_value for
numeric fields like Integer and Float allow developers to specify constraints
directly in the model's definition.

### Container Fields

Container fields are used for data types that hold multiple values, such as
lists and dictionaries. These fields support complex structures and provide
options such as `content_type` for `List` fields to ensure type consistency
within the collection. Protean optimizes storage and retrieval operations for
these fields by leveraging database-specific features when available.

### Association Fields

Association fields define relationships between different domain models,
such as one-to-one, one-to-many, and many-to-many associations. These fields
help in mapping complex domain relationships and include functionalities to
manage related objects efficiently, preserving data integrity across the domain.


<!-- Be careful not to choose field names that conflict with the
[Data Container API](../../api/data-containers) like `clean`, `clone`, or
`to_dict`. -->