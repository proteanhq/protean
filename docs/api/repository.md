# BaseRepository

Base class for repositories, the persistence abstraction for aggregates.
Repositories provide a collection-oriented interface (`add`, `get`, `all`) to
load and persist aggregates. The interface keeps database details out of your
domain code.

See [Repositories guide](../guides/change-state/repositories.md) for practical
usage and [Repositories concept](../concepts/building-blocks/repositories.md)
for design rationale.

::: protean.core.repository.BaseRepository
    options:
      show_root_heading: false
      inherited_members: false
