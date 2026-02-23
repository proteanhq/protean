# Domain

The central registry object. Create one per bounded context to register all
domain elements, manage configuration, and coordinate infrastructure adapters.

See [Compose a Domain](../guides/compose-a-domain/index.md) for a practical guide.

::: protean.domain.Domain
    options:
      show_root_heading: false
      members:
        - __init__
        - init
        - domain_context
        - has_outbox
        - camel_case_name
        - normalized_name
        - aggregate
        - entity
        - value_object
        - command
        - event
        - command_handler
        - event_handler
        - application_service
        - domain_service
        - repository
        - projection
        - projector
        - subscriber
        - process_manager
        - upcaster
        - database_model
        - process
      filters: []
