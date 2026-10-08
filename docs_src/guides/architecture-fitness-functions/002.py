# --8<-- [start:rule]
# my_app/lint.py
def check_naming(ir: dict) -> list[dict]:
    """Flag aggregates whose short name is not PascalCase."""
    findings = []
    # ir["elements"] is a flat index of element type -> list of FQNs.
    for fqn in ir.get("elements", {}).get("AGGREGATE", []):
        name = fqn.rsplit(".", 1)[-1]
        if not (name[:1].isupper() and name.isalnum()):
            findings.append(
                {
                    "code": "AGGREGATE_NOT_PASCAL_CASE",
                    "element": fqn,
                    "level": "info",
                    "message": f"{name} should be PascalCase",
                }
            )
    return findings


# --8<-- [end:rule]
