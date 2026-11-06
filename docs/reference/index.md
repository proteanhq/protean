# Look up Protean's options and APIs

The reference section is factual documentation of Protean's components,
arranged for lookup. Use it to find specific configuration options, field
types, CLI commands, adapter settings, and API details.

For an explanation of *why* Protean works as it does, see
[Concepts](../concepts/index.md). For step-by-step *how-to* instructions, see
[Guides](../guides/index.md).

<div class="grid cards" markdown>

-   **:material-code-tags: Configure domain elements**

    ---

    Decorator options, meta attributes, reflection API, identity
    configuration.

    [:material-arrow-right-box: Element Decorators](domain-elements/element-decorators.md)
    [:material-arrow-right-box: Object Model](domain-elements/object-model.md)
    [:material-arrow-right-box: Identity](domain-elements/identity.md)

-   **:material-form-textbox: Choose a field type**

    ---

    All field types, arguments, and definition styles.

    [:material-arrow-right-box: Fields](fields/index.md)

-   **:material-cog: Configure a domain**

    ---

    `domain.toml` parameters, environment overlays, adapter configuration.

    [:material-arrow-right-box: Configuration](configuration/index.md)

-   **:material-file-document-outline: Configure logging**

    ---

    `[logging]` config schema, CLI flags, framework logger catalog, wide
    event field schemas, redaction, trace-context fields.

    [:material-arrow-right-box: Logging](logging.md)

-   **:material-console: Run CLI commands**

    ---

    All `protean` CLI commands and their options.

    [:material-arrow-right-box: CLI Commands](cli/index.md)

-   **:material-server: Run the server**

    ---

    Subscription types, profiles, multi-worker mode, observability.

    [:material-arrow-right-box: Subscription Types](server/subscription-types.md)
    [:material-arrow-right-box: Configuration](server/configuration.md)
    [:material-arrow-right-box: Multi-Worker](server/supervisor.md)
    [:material-arrow-right-box: Observability](server/observability.md)

-   **:material-puzzle: Configure adapters**

    ---

    Database, broker, cache, and event store adapter configuration.

    [:material-arrow-right-box: Adapters](adapters/index.md)

-   **:material-language-python: Set up type checking**

    ---

    Mypy plugin setup and configuration.

    [:material-arrow-right-box: Type Checking](type-checking/index.md)

-   **:material-test-tube: Test with pytest**

    ---

    Pytest plugin, `--protean-env` option, and test fixtures.

    [:material-arrow-right-box: Pytest Plugin](testing/pytest-plugin.md)

-   **:material-swap-horizontal: Migrate between versions**

    ---

    Version migration guides.

    [:material-arrow-right-box: Migration guides](migration/index.md)

-   **:material-api: Look up the Python API**

    ---

    Auto-generated class signatures, method parameters, and return types
    from source code.

    [:material-arrow-right-box: API Reference](../api/index.md)

-   **:material-map-marker-check: Check where Protean fits**

    ---

    Which systems Protean fits and which it does not. Each case states the
    reason.

    [:material-arrow-right-box: Applicability Charter](applicability.md)

-   **:material-shield-check: Check what each port and adapter guarantees**

    ---

    Per-port, per-adapter ordering, delivery, consistency, and isolation. This
    is the contract the conformance tests check against.

    [:material-arrow-right-box: Guarantees](guarantees.md)

-   **:material-tag-outline: Read the versioning policy**

    ---

    What Protean promises with each version number. How to enforce that promise
    in your own CI.

    [:material-arrow-right-box: Versioning Policy](versioning-policy.md)

-   **:material-format-list-checks: Find which names are stable**

    ---

    Which names the compatibility contract covers: Stable, Provisional, or
    Internal.

    [:material-arrow-right-box: Stable Surface](stable-surface.md)

-   **:material-security: Review security considerations**

    ---

    Protean's security posture: input handling, field sanitization defaults,
    persistence, secrets in configuration, the network services it ships, and
    what is left to the operator.

    [:material-arrow-right-box: Security Considerations](security.md)

</div>
