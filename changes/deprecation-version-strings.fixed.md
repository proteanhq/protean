**Breaking.** [IR] `deprecated=` raises `ConfigurationError` when `since` or `removal` is a number, and `protean ir diff` exits 1 on an IR file that holds a numeric `removal` for a removed published event or field. A number lost its trailing zero, so `removal: 0.20` was read as `"0.2"` and the field was classed as safe to remove in 0.18.

**Migration:** [Deprecation versions must be strings](https://docs.proteanhq.com/reference/migration/v0-19/#deprecation-versions-must-be-strings)
