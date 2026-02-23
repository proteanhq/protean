# BaseRepository

Base class for repositories -- the persistence abstraction for aggregates.
Repositories provide a collection-oriented interface (`add`, `get`, `all`)
to load and persist aggregates, hiding database details behind a clean domain API.

See [Repositories guide](../guides/change-state/repositories.md) for practical
usage and [Repositories concept](../concepts/building-blocks/repositories.md)
for design rationale.

::: protean.core.repository.BaseRepository
    options:
      show_root_heading: false
      inherited_members: false
