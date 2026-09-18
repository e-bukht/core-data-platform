# Security policy — Phase 0 skeleton

- Never commit secrets, private keys, production credentials, tokens, or `.env`.
- Runtime DB users must not be PostgreSQL superusers.
- Security scans in CI are merge gates according to project policy.
- Report vulnerabilities through the private security channel configured by the repository owner.
- Authentication/authorization is intentionally introduced in P0-I2; P0-I1 endpoints are technical
  and must not be exposed directly to the public Internet.
