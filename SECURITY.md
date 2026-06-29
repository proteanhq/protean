# Security Policy

## Supported versions

Protean is pre-1.0. To keep the maintenance surface small while the API is still
evolving, **only the latest minor release line receives security and bug-fix
patches.** Patches are shipped from the corresponding `release/0.X.x` branch
(for example, `release/0.16.x` for the 0.16 line).

| Version | Supported          |
| ------- | ------------------ |
| 0.16.x  | :white_check_mark: |
| < 0.16  | :x:                |

When a new minor ships, the previous line stops receiving patches. Upgrading to
the latest minor is the supported path for picking up fixes. Each minor follows
the tiered breaking-change policy in
[ADR-0004](docs/adr/0004-release-workflow-and-breaking-change-policy.md), so
upgrades within the supported window come with deprecation warnings and upgrade
notes rather than silent breaks.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's
[private vulnerability reporting](https://github.com/proteanhq/protean/security/advisories/new)
("Report a vulnerability" under the repository's **Security** tab). If you cannot
use GitHub advisories, email the maintainer at
**subhash.bhushan@gmail.com** with `[protean-security]` in the subject.

Please include:

- The affected version(s) and a description of the issue.
- Steps to reproduce, or a proof-of-concept, where possible.
- The impact you foresee (data exposure, RCE, denial of service, etc.).

### What to expect

- **Acknowledgement** within 3 business days.
- An initial assessment and severity classification within 7 days.
- A coordinated fix on the supported release line, shipped as a patch release,
  followed by a public advisory crediting the reporter (unless anonymity is
  requested).

Thank you for helping keep Protean and its users safe.
