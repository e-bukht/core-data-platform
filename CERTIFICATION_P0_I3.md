# P0-I3 Transaction Kernel - Certification Record

Status: **CERTIFIED - PASS WITH OBSERVATIONS - GO P0-I4**

Certification date: 2026-09-24
Implementation contract: `architecture/contracts/transaction-kernel.md`

## Certified environment

- OS: Windows 11
- Python: CPython 3.12.4
- pytest: 9.0.3
- PostgreSQL compatibility floor: 12.22
- PostgreSQL reference: 18
- Database runtime isolation: PostgreSQL RLS with FORCE ROW LEVEL SECURITY
- Runtime role: non-owner, NOSUPERUSER, NOBYPASSRLS
- Migration head: `0003_transaction_kernel`

## Certification matrix

| ID | Criterion | Status | Evidence |
|---|---|---|---|
| C-I3-01 | UoW commits business state, idempotency, outbox and audit atomically. | PASS | `test_transaction_kernel_unit_of_work` commits the test business probe, IdempotencyRecord, OutboxMessage and AuditRecord in the same PostgreSQL transaction on PostgreSQL 12.22 and 18. |
| C-I3-02 | Rollback leaves no partial effects. | PASS | Explicit no-commit and exception paths roll back business state, idempotency, outbox and audit together on both supported PostgreSQL versions. |
| C-I3-03 | Transaction inherits tenant, actor and correlation context while RLS remains independent. | PASS | UoW integration verifies transaction-local `app.current_tenant_id`, `app.current_actor_id` and `app.current_correlation_id`; FORCE RLS matrix remains green. |
| C-I3-04 | First idempotency key executes one business effect. | PASS | Idempotency unit and integration tests verify first-use execution and one committed effect. |
| C-I3-05 | Same key and same request hash replay without duplicate business effect. | PASS | Completed idempotency records return REPLAY for the same request hash; integration proof confirms no second committed effect. |
| C-I3-06 | Same key with a different request hash is rejected. | PASS | `test_same_key_with_different_request_is_rejected` passes with `IdempotencyKeyConflictError`. |
| C-I3-07 | Concurrent requests using the same idempotency key produce one committed effect. | PASS | PostgreSQL concurrency test runs two contenders against the same `(tenant, operation, key)` and proves one committed business effect on PostgreSQL 12.22 and 18. |
| C-I3-08 | Rollback or crash before commit does not strand the idempotency key; retry remains possible. | PASS | Integration test rolls back the first attempt, verifies the record is absent, then retries successfully with one final committed effect. |
| C-I3-09 | Optimistic expected-version CAS detects stale writes. | PASS | Concurrent CAS test proves one writer advances version 0 -> 1, the stale writer receives `ConcurrencyConflict`, and cross-tenant attempts expose no existence/version information on PostgreSQL 12.22 and 18. |
| C-I3-10 | Outbox persistence is atomic with business state. | PASS | UoW atomicity tests prove OutboxMessage commit/rollback follows the enclosing business transaction. |
| C-I3-11 | Concurrent Outbox dispatchers do not claim the same message. | PASS | `FOR UPDATE SKIP LOCKED` concurrency proof returns distinct claims to concurrent workers on PostgreSQL 12.22 and 18. |
| C-I3-12 | Expired lease or publish failure permits retry. | PASS | Outbox release/reclaim and lease-expiry tests prove a failed or abandoned attempt can be claimed again with a new attempt number. |
| C-I3-13 | First Inbox delivery is processed normally. | PASS | Inbox integration test records the Inbox entry and exactly one business effect atomically on PostgreSQL 12.22 and 18. |
| C-I3-14 | Duplicate Inbox delivery does not produce a second business effect. | PASS | Sequential duplicate and forced concurrent collision tests both leave exactly one business effect. The test business table has no `(tenant_id, message_id)` uniqueness guard, so deduplication is proven at the Inbox transaction boundary. |
| C-I3-15 | Handler failure rolls back Inbox registration and business effect; retry succeeds. | PASS | Simulated handler failure leaves no Inbox record and no business effect; retry processes normally and commits one effect. |
| C-I3-16 | MessageEnvelope preserves transaction and message context and deterministic payload hash. | PASS | Unit tests verify tenant, actor, transaction, correlation, causation, aggregate metadata, schema version and canonical SHA-256 payload hashing. |
| C-I3-17 | Durable audit is atomic, append-only and correlated. | PASS | Dedicated audit tests verify commit/rollback correlation; runtime has SELECT/INSERT only, and database trigger rejects UPDATE/DELETE, including privileged mutation attempts, on PostgreSQL 12.22 and 18. |
| C-I3-18 | Architecture, Ruff, mypy, pytest, security scans and SBOM are green. | PASS | Ruff PASS; format PASS; mypy strict 107 source files/0 errors; Import Linter 4 contracts kept/0 broken; final pytest 109/109; pip-audit no known vulnerabilities; Bandit no findings; Gitleaks worktree no leaks; runtime/full CycloneDX SBOM generated and hashed. |
| C-I3-19 | Fresh and upgrade migrations pass on PostgreSQL 12.22 and 18. | PASS | Fresh migration, P0-I1 -> current head and explicit `0002_context_trust -> 0003_transaction_kernel` paths all pass on PostgreSQL 12.22 and 18 while preserving representative P0-I2 data. |
| C-I3-20 | Local crash/retry/replay demonstrates at-least-once delivery and effectively-once business effect. | PASS | Crash-after-publish-before-mark simulation republishes the same Outbox message after lease expiry; Inbox recognizes redelivery and business effect remains exactly one before Outbox is marked published. |

## Transaction Kernel invariants certified

The certification establishes the following implementation properties:

- every state-changing command executes through an explicit Unit of Work;
- tenant, actor and correlation identity originate from verified execution context;
- state, durable audit and Outbox persistence share the same local atomic transaction;
- idempotency scope is `(tenant_id, operation, idempotency_key)`;
- an idempotency key remains bound to one request hash while its record exists;
- optimistic writes require an expected version and fail closed on stale or invisible rows;
- Outbox transport semantics are at-least-once, not global exactly-once;
- Inbox registration and business effect are atomic, providing effectively-once business effects;
- every Transaction Kernel persistence table is tenant scoped with ENABLE and FORCE RLS;
- runtime database access remains non-owner and without SUPERUSER or BYPASSRLS;
- durable AuditRecord persistence is append-only at the database boundary;
- the kernel remains broker-agnostic.

## PostgreSQL certification evidence

Transaction Kernel integration suites pass against:

- PostgreSQL 12.22
- PostgreSQL 18

Certified tenant-scoped Transaction Kernel tables:

- `platform.idempotency_record`
- `platform.outbox_message`
- `platform.inbox_message`
- `platform.audit_record`

Each table is protected by PostgreSQL ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY.

The runtime role remains non-owner, NOSUPERUSER and NOBYPASSRLS.

## Migration evidence

Certified migration paths:

- fresh database -> `0003_transaction_kernel` on PostgreSQL 12.22
- fresh database -> `0003_transaction_kernel` on PostgreSQL 18
- P0-I1 `0001_bootstrap_platform` -> current head on PostgreSQL 12.22
- P0-I1 `0001_bootstrap_platform` -> current head on PostgreSQL 18
- exact P0-I2 `0002_context_trust` -> `0003_transaction_kernel` on PostgreSQL 12.22
- exact P0-I2 `0002_context_trust` -> `0003_transaction_kernel` on PostgreSQL 18

The exact P0-I2 upgrade proof verifies preservation of representative pre-existing Tenant and Actor data and creation of all four Transaction Kernel tables.

## Quality and security evidence

Final certification evidence:

- Ruff check: PASS
- Ruff format check: PASS
- mypy strict: 107 source files, 0 errors
- Import Linter: 4 contracts kept, 0 broken
- pytest final regression: 109 passed
- pytest dependency warnings: 2 non-blocking FastAPI/Starlette deprecation warnings
- pip-audit: no known vulnerabilities
- Bandit: no findings
- Gitleaks worktree: no leaks
- Gitleaks worktree scan: 150 files, 671062 bytes
- Gitleaks container digest: `sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f`
- Runtime CycloneDX SBOM: `.sbom/runtime.cdx.json`
- Runtime SBOM SHA256: `7A267D62ED10E773084C47F1264925B02ECD443DD0B228DA6D2F5CDFA333973B`
- Full CycloneDX SBOM: `.sbom/full.cdx.json`
- Full SBOM SHA256: `ADEFC33F642D362A011DAC14B2D86AD7FB4DC85D4C8C357127D7950F4E47FDAE`

`pip-audit` reports the local `core-data-platform` package itself as unavailable on PyPI; third-party auditable dependencies contain no known vulnerabilities.

## Delivery semantics evidence

The certified local Outbox/Inbox path demonstrates:

business transaction
-> durable OutboxMessage
-> dispatcher claim with bounded lease
-> publish
-> simulated crash before mark-published
-> lease expiry
-> redelivery
-> duplicate Inbox recognition
-> no duplicate business effect
-> successful final mark-published.

This establishes at-least-once message delivery with effectively-once business effect. It does not claim distributed or global exactly-once transport.

## Observations

1. Local CPython is 3.12.4. The project remains on the certified Python 3.12 minor line; patch-level alignment can be handled independently.
2. pytest reports two dependency deprecation warnings involving FastAPI/Starlette TestClient internals. They remain non-blocking for P0-I3.
3. Windows async Psycopg execution continues to require a SelectorEventLoop in the certification harness.
4. Gitleaks is executed through its container image because a workstation-local Gitleaks binary is not required by the repository.
5. Production broker integration, Saga/Process Manager, reconciliation/repair, generalized DLQ administration, cryptographic Evidence and distributed exactly-once semantics remain intentionally outside P0-I3 scope.

## Final decision

All C-I3-01 through C-I3-20 technical criteria are satisfied.

No unresolved cross-tenant leak, partial atomic commit, idempotency double-effect, stale-version overwrite, duplicate Inbox business effect or runtime audit-mutation finding remains.

P0-I3 establishes the certified local Transaction Kernel foundation for Unit of Work, idempotency, optimistic concurrency, transactional Outbox/Inbox and durable append-only audit.

The repository seal for this record consists of the final secret scan, Git integrity check, certification commit and post-commit clean-working-tree verification.

**P0-I3 PASS WITH OBSERVATIONS - GO P0-I4**
