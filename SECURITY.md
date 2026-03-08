# Security Policy

## Scope

MailAtlas processes email-like data, attachments, and HTML content. Treat fixture
quality, parser safety, and local data handling as security-sensitive areas.

## Supported Versions

Security fixes are targeted at the latest tagged release and the main development branch.

## Reporting

Do not open public GitHub issues for suspected security problems.

Report vulnerabilities to `hello@mailatlas.dev` with:

- affected version or commit
- reproduction steps or sample payload
- impact assessment
- any proposed mitigation

We will acknowledge reports, investigate them privately, and publish a fix or advisory when appropriate.

## Safe Contribution Rules

- Do not add private inbox data or third-party newsletter archives to the repo.
- Keep fixtures synthetic or fully scrubbed.
- Avoid changes that silently weaken provenance or content-cleaning guarantees.
