# Fields

Field types for declaring attributes on domain elements (aggregates, entities,
value objects, commands, events, and projections).

See the hand-written [Fields Reference](../../reference/fields/index.md) for
usage examples, definition styles, and field arguments table.

<div class="grid cards" markdown>

-   **:material-format-text: Simple Fields**

    ---

    Scalar field factories: String, Integer, Float, Boolean, Date, DateTime, and more.

    [:material-arrow-right-box: Simple Fields](simple.md)

-   **:material-code-array: Container Fields**

    ---

    List and Dict fields for collection-typed attributes.

    [:material-arrow-right-box: Container Fields](containers.md)

-   **:material-link-variant: Association Fields**

    ---

    HasOne, HasMany, and Reference for relationships between domain elements.

    [:material-arrow-right-box: Association Fields](association.md)

-   **:material-cube-outline: ValueObject Field**

    ---

    Field descriptor for embedding value objects within aggregates or entities.

    [:material-arrow-right-box: ValueObject Field](embedded.md)

-   **:material-cog: FieldSpec**

    ---

    The internal field declaration carrier that all field factories produce.

    [:material-arrow-right-box: FieldSpec](spec.md)

</div>
