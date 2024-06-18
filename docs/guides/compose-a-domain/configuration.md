# Configuratiion

## Primary Configuration Attributes

### `environment`

The `environment` attribute specifies the current running environment of the
application. By default, the environment is `development`. The current
environment can be gathered from an environment variable called `PROTEAN_ENV`.

Protean recognizes `development` and `production` environments, but additional
environments such as `pre-prod`, `staging`, and `testing` can be specified as
needed.

- **Default Value**: `development`
- **Environment Variable**: `PROTEAN_ENV`
- **Examples**:
  - `development`
  - `production`
  - `pre-prod`
  - `staging`
  - `testing`

### `debug`

### `testing`

### `secret_key`

## Domain Configuration Attributes

### `identity_strategy`

### `identity_type`

### `command_processing`

### `event_processing`

### `snapshot_threshold`

## Adapter Configuration

### `database`

### `cache`

### `broker`

### `event_store`