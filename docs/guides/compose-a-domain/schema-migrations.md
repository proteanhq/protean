# Run Schema Migrations

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

A schema migration is a versioned script that changes the tables in a
database. Protean writes and runs these scripts with
[Alembic](https://alembic.sqlalchemy.org/), through the `protean db` commands.
This guide follows one change from the dev box, through CI, to production.

`protean db setup` creates the tables that are missing and never changes a
table that exists. Once a database holds data, a new field needs a migration.

Migrations work on the `postgresql`, `sqlite`, `mssql` and `mysql` providers.
The extras of the same name install Alembic. The memory and Elasticsearch
providers have no migrations.

---

## Change a table on the dev box

Run the commands from the project root, the folder that holds the domain. Each
command finds the domain there, as `--domain` defaults to the current folder.

Create the migrations folder for the `default` provider once per project:

```bash
protean db init
```

The command writes `migrations/alembic.ini`, `migrations/env.py`, a template
and an empty `migrations/versions/` folder. A project that
[`protean new`](../../reference/cli/project/new.md#schema-migrations) created
on the `postgresql`, `sqlite` or `mssql` database already has the folder.

Change the model, for example add a field to an aggregate, and write a
migration for the change:

```bash
protean db migrate -m "add price to product"
```

The command compares the domain's tables with the dev database, writes a file
into `migrations/versions/` and prints its path. When nothing differs, it
prints `No changes detected; no migration written.` and writes no file.

Read the file before you go on. It holds an `upgrade()` function that makes the
change and a `downgrade()` function that undoes it. Fix what autogenerate got
wrong; the next section lists what it misses. Then commit the file in the
same commit as the model change.

Apply the migration to the dev database:

```bash
protean db upgrade
```

To undo the last migration on the dev box, run `protean db downgrade -1`, edit
the file, and run `protean db upgrade` again.

---

## Know what autogenerate cannot do

`protean db migrate` uses Alembic's autogenerate feature. It compares the
tables the domain declares with the tables in the database, and it reads
nothing else. Every migration file needs a review, because:

- **A renamed field shows as a drop and an add.** Rename a field, and the
  migration drops the old column and adds a new, empty one. The data is lost.
  Replace the two operations with `op.alter_column(...,
  new_column_name=...)`. On SQLite, autogenerate writes column changes inside
  a `with op.batch_alter_table(...) as batch_op:` block; there, write
  `batch_op.alter_column(..., new_column_name=...)`.
- **A renamed aggregate shows as a new table.** Rename an aggregate, and the
  migration creates a new, empty table and leaves the old one in place.
  Replace `op.create_table(...)` with `op.rename_table(old_name, new_name)`.
- **Some changes go undetected.** A changed server default is not compared.
  Some type changes are missed, depending on the database. Alembic lists these
  in its
  [autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect).
- **Data migrations are written by hand.** Autogenerate changes the schema
  only. To fill a new column from an old one, or to split a column, add the
  `op.execute(...)` statements to the file yourself.
- **MySQL and SQLite keep the DDL that ran before a failure.** Alembic runs
  them without transactional DDL. A migration that fails half-way leaves its
  earlier statements applied, and the database is between two revisions. Keep
  each migration on these databases small, so a failure is easy to repair by
  hand. PostgreSQL and SQL Server run DDL in a transaction, and
  `protean db upgrade` applies all pending migrations in one transaction. A
  failure there rolls back every migration of that run, including the ones
  that had already succeeded.

For a change autogenerate cannot write, such as a data migration on its own,
create an empty migration with Alembic and fill in `upgrade()` and
`downgrade()`:

```bash
alembic -c migrations/alembic.ini revision -m "split full name"
```

---

## Keep tests on `create_all` and check migrations in CI

Tests do not run migrations. The test fixtures and `protean db setup` create
the tables straight from the model with SQLAlchemy's `create_all`, which is
fast and needs no migration history. See
[Setting Up and Tearing Down Databases for Tests](../../patterns/setting-up-and-tearing-down-database-for-tests.md).

CI checks that the committed migrations match the model. Point the domain at a
database with no tables, then run:

```bash
protean db upgrade
protean db check
```

`protean db upgrade` applies every migration, so a broken migration fails the
job. `protean db check` then compares the database with the model and exits
with one of three codes:

| Code | Meaning |
|------|---------|
| `0` | The database matches the table definitions. |
| `1` | The database differs, so a model change has no migration. The differences are on stdout. |
| `2` | The command could not compare, for example the database is unreachable. The message is on stderr. |

On exit 1, run `protean db migrate` on the dev box and commit the file. A
project from `protean new` already has this CI step. It runs after the tests,
on the test database, once the test fixtures have dropped their tables; see
[Schema migrations](../../reference/cli/project/new.md#schema-migrations).

---

## Apply migrations to production

Pick one of three paths. Each one applies the same committed files.

### Print the SQL and run it by hand

Use this path when a database administrator reviews and runs every change.
Print the SQL from the revision production is at to the latest one:

```bash
protean db upgrade <current>:head --sql > upgrade.sql
```

`<current>` is the revision production is at, the value in its
`alembic_version` table. With `--sql`, the command does not connect to the
database, so it cannot read that revision itself. Without the range, it prints
the script for an empty database, which creates every table from the first
migration on. Always pass the range for a database that has tables. After
the SQL of each migration, the script updates `alembic_version`, so the
database records the revision it is at once the script has run.

Review `upgrade.sql` and run it with the database's own client.

### Run `protean db upgrade` from the deploy job

Use this path when the deploy job may change the schema. Run the command once
per deploy, before the new code starts:

```bash
PROTEAN_ENV=production protean db upgrade
```

`PROTEAN_ENV` selects the production overlay of `domain.toml`; see
[Configure for Production](production-configuration.md#environment-overlays).
Run the command from one job, not from every application instance, so two
instances never apply the same migration at the same time.

### Feed your own migration tool

Use this path when the team runs a migration tool of its own. Every SQL
provider has a public `metadata` property. It returns the SQLAlchemy
`MetaData` that holds every table the provider owns, and the tool reads the
table definitions from it:

```python
--8<-- "guides/compose-a-domain/schema-migrations/001.py:full"
```

Reading the property does not connect to the database, but `domain.init()`
does, so the database must be reachable. Read the property after
`domain.init()`, inside a domain context. The
[database adapters reference](../../reference/adapters/database/index.md#read-the-tables-a-sql-provider-owns)
lists which tables it holds.

---

## Adopt migrations on an existing database

A database that `protean db setup` created has its tables and no migration
history. Bring it under migrations in two steps:

1. Write the initial migration against an empty dev database. Point the
   domain at a database with no tables, run `protean db init` and then
   `protean db migrate -m "initial schema"`. The migration creates every
   table.
2. Mark the existing database as already at that revision. Point the domain
   at the existing database and run Alembic's `stamp` command:

    ```bash
    alembic -c migrations/alembic.ini stamp head
    ```

    `stamp` writes the revision into `alembic_version` and changes no table.

Protean has no `stamp` command of its own. Alembic's `stamp` reads the same
`migrations/alembic.ini`. From then on, run `protean db upgrade` on that database.
Run `protean db check` after the stamp to confirm the tables match the model.

Do not mix `protean db setup` and migrations on one database. `setup` creates
tables without recording a revision, so a later `protean db upgrade` tries to
create the same tables again and fails. Tests keep `setup`, and every other
database uses `upgrade`.

---

## Give each provider its own folder

A domain with more than one database provider keeps one migrations folder per
provider:

```toml
--8<-- "guides/compose-a-domain/schema-migrations/two_providers.toml"
```

Create a folder for the second provider with `--provider` and `--directory`,
and pass the folder to the later commands:

```bash
protean db init --provider=reporting --directory=migrations/reporting
protean db migrate -m "create report tables" --directory=migrations/reporting
protean db upgrade --directory=migrations/reporting
```

`init` records the provider's name in the folder's `alembic.ini`. The later
commands read it from there, so they take `--directory` and no `--provider`:

```ini
# migrations/reporting/alembic.ini
protean_domain = .
protean_provider = reporting
protean_root = %(here)s/../..
```

---

## Drop tables by hand

A migration only touches the tables the provider owns. `protean db migrate`
never drops a table that the domain does not declare, and `protean db check`
never reports one. A table that another application writes stays as it is,
and so does Alembic's own `alembic_version` table.

For the same reason, removing an aggregate does not drop its table. To drop it,
write a migration by hand with `alembic revision`, as above, and call
`op.drop_table(...)` in its `upgrade()`.

---

## Write a changed raw index by hand

An index declared with
[`Index.from_sql`](../../reference/domain-elements/indexes.md#indexfrom_sql)
goes into the migration that creates its table. A named raw index added to an
existing table gets a migration that creates it by name. An index declared for
another database is left out.

Autogenerate compares raw indexes by name only. Change the SQL of a raw index
and keep its name, and `protean db migrate` sees no change. Write that
migration by hand: drop the index and create it again with the new SQL.

---

## Write a changed partial-index condition by hand

Autogenerate does not compare the `where=` condition of a
[partial index](../domain-definition/indexes.md#partial-indexes). Change the
condition and `protean db migrate` sees no change. Write the migration by
hand: drop the index and create it again with the new condition.

---

## Know where `protean upgrade-check` fits

[`protean upgrade-check`](../../reference/cli/upgrade-check.md) reports what
needs attention when you move to a newer Protean release. For a change to
Protean's own tables, such as `outbox`, it prints the SQL to run.

With migrations, Protean's own tables are part of the provider's `metadata`
when the domain uses them, for example the `outbox` table when the outbox is
enabled. A change to their columns or indexes arrives in your next
`protean db migrate` like any model change. Autogenerate writes only the
schema change. When a change needs existing rows filled first, such as
`OUTBOX_TARGET_BROKER_NULLABLE`, copy the backfill SQL that
`protean upgrade-check` prints into the migration's `upgrade()`, before the
schema change. `protean upgrade-check` also stays for teams that do not use
migrations, and its other checks apply to every team.

---

!!! seealso "See also"
    - [`protean db`](../../reference/cli/data/database.md): Every command and
      option used on this page.
    - [Configure for Production](production-configuration.md): Environment
      overlays and adapter configuration.
    - [Declaring Indexes](../domain-definition/indexes.md): Index options and
      dialect support.
