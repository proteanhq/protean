# GitHub Project API Reference

Canonical reference for project-board automation on GitHub Project #15 (private,
`proteanhq` org). Useful GraphQL mutations, queries, and the field/option IDs.

Project ID: `PVT_kwDOAmXm_s4BRFMC`.

## Mutations

**Convert a draft item to a real issue** (preserves all project fields):
```
mutation { convertProjectV2DraftIssueItemToIssue(input: {
  projectId: "PVT_kwDOAmXm_s4BRFMC"
  itemId: "<draft-item-id>"
  repositoryId: "<repo-node-id>"
}) { item { id } } }
```

**Set a field value on a project item** (works for Status, Capability, Sequence, Requires, Item Type):
```
mutation { updateProjectV2ItemFieldValue(input: {
  projectId: "PVT_kwDOAmXm_s4BRFMC"
  itemId: "<item-id>"
  fieldId: "<field-id>"
  value: { singleSelectOptionId: "<option-id>" }  # or: { text: "..." } / { number: N }
}) { projectV2Item { id } } }
```

**Add a blocked-by relationship between two real issues** (`issueId` is the blocked one):
```
mutation { addBlockedBy(input: {
  issueId: "<blocked-issue-node-id>"
  blockingIssueId: "<blocking-issue-node-id>"
}) { issue { number } blockingIssue { number } } }
```
Returns "already taken" validation error if the relationship already exists — safe to treat as a no-op.

## Queries

**Query blocked-by/blocking on an issue:**
```
{ repository(owner: "proteanhq", name: "protean") {
  issue(number: N) {
    blockedBy(first: 10) { nodes { number title } }
    blocking(first: 10) { nodes { number title } }
  }
} }
```

## Key field IDs (project #15)

| Field | ID | Notes |
|-------|----|-------|
| Status | `PVTSSF_lADOAmXm_s4BRFMCzg_A5gY` | Backlog=`f75ad846`, Active=`5a1d9210`, In Progress=`47fc9ee4`, Done=`98236657` |
| Item Type | `PVTSSF_lADOAmXm_s4BRFMCzg_KRSg` | Epic=`1acf4758`, Task=`ae8e6519` |
| Capability | `PVTSSF_lADOAmXm_s4BRFMCzg_A5uY` | Knows Itself=`3251b733`, Explains Itself=`36a2deff`, Shows Itself=`76850904`, Exposes Itself=`258cdab9`, Builds Itself=`5931373c`, Deploys Itself=`d1e4e43d` |
| Sequence | `PVTF_lADOAmXm_s4BRFMCzg_kOnU` | Number field (1–37 global execution order) |
| Requires | `PVTF_lADOAmXm_s4BRFMCzg_kQTc` | Text field, e.g. `"1.1, 1.6"` |

> The Capability field was renamed from "Release" (options R1–R6) on 2026-04-26.
> Use "Capability" everywhere; the field ID is unchanged.
