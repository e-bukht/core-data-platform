# Release notes - P0-I3 Transaction Kernel

## Added

- Pure `core_platform.transaction_kernel` kernel with TransactionContext, transaction identifiers, records and persistence ports.
- Explicit Unit of Work with rollback-by-default and fail-fast nested root transaction protection.
- Transaction-scoped propagation of verified tenant, actor and correlation context.
- PostgreSQL-backed idempotency with canonical request hashing and concurrency-safe uniqueness.
- Generic optimistic concurrency compare-and-swap persistence helper.
- MessageEnvelope construction with canonical SHA-256 payload hashing.
- Transactional Outbox with `FOR UPDATE SKIP LOCKED`, bounded leases and fenced mark/release operations.
- Inbox deduplication with atomic Inbox registration and business-effect persistence.
- Durable append-only AuditRecord foundation.
- Alembic revision `0003_transaction_kernel`.
- FORCE RLS policies for all Transaction Kernel tenant-scoped persistence.
- PostgreSQL 12.22 / 18 Transaction Kernel integration and concurrency tests.
- Explicit P0-I2 `0002_context_trust` -> P0-I3 `0003_transaction_kernel` upgrade certification.
- Crash/retry/replay certification proving at-least-once delivery with effectively-once business effect.
- P0-I3 certification record covering C-I3-01 through C-I3-20.

## Transaction semantics

State-changing operations use an explicit Unit of Work.

Where applicable, business state, idempotency state, durable audit and Outbox messages commit atomically in the same PostgreSQL transaction.

Idempotency keys are scoped by tenant and operation and remain bound to a deterministic request hash.

Optimistic concurrency uses expected-version compare-and-swap writes. A stale or invisible row produces a generic `ConcurrencyConflict` without exposing actual version or cross-tenant existence.

## Messaging semantics

The Transaction Kernel guarantees local transactional Outbox persistence and Inbox-based duplicate suppression.

The certified delivery model is:

- at-least-once transport;
- bounded Outbox leases;
- retry after publish failure or dispatcher crash;
- duplicate delivery permitted;
- effectively-once business effect when Inbox registration and the handler effect share the same Unit of Work.

P0-I3 does not claim global exactly-once delivery or distributed transactions.

## Audit

`platform.audit_record` is durable and tenant scoped.

Runtime access is limited to INSERT and SELECT. UPDATE and DELETE are revoked, and a database trigger rejects audit mutation even through a more privileged database path.

Cryptographic Evidence, hash chaining and signatures remain outside P0-I3 scope.

## Upgrade compatibility

Alembic revision `0003_transaction_kernel` is certified on:

- fresh PostgreSQL 12.22 and 18 databases;
- existing P0-I1 databases upgraded to current head;
- exact P0-I2 `0002_context_trust` databases upgraded to `0003_transaction_kernel`.

The P0-I2 -> P0-I3 certification preserves representative existing Tenant and Actor data.

## Certification state

P0-I3 is **CERTIFIED - PASS WITH OBSERVATIONS - GO P0-I4**.

All C-I3-01 through C-I3-20 criteria pass on the certified workstation.

Known non-blocking observations are recorded in `CERTIFICATION_P0_I3.md`.
