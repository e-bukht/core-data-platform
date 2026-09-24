# P0-I3 Transaction Kernel Contract

Status: IMPLEMENTATION CONTRACT
Version: 1.0
Date: 2026-09-21
Prerequisite: P0-I2 Context & Trust certified at tag `p0-i2-certified`

## Scope

P0-I3 introduces the first production-grade Transaction Kernel:

- Unit of Work
- TransactionContext
- idempotency
- optimistic concurrency
- MessageEnvelope
- transactional Outbox
- transactional Inbox
- durable append-only Audit foundation

## Core invariants

1. Every state-changing command executes inside one explicit UnitOfWork.
2. Tenant, Actor and correlation identity come from the verified ExecutionContext, never from command payloads.
3. Domain state, durable audit and outbox records commit atomically whenever the command emits them.
4. Rollback leaves none of those effects committed.
5. Idempotency is scoped by `(tenant_id, operation, idempotency_key)`.
6. An idempotency key is permanently associated with its canonical request hash for the record lifetime.
7. Reusing a key with a different request hash is rejected.
8. Concurrent execution of the same idempotent command produces at most one committed business effect.
9. Optimistic writes use atomic expected-version comparison.
10. Outbox delivery is at-least-once.
11. Inbox processing provides effectively-once business effects when inbox registration and handler effects share one transaction.
12. No global exactly-once delivery guarantee is claimed.
13. All tenant-scoped Transaction Kernel tables use PostgreSQL ENABLE + FORCE ROW LEVEL SECURITY.
14. The runtime role remains non-owner, NOSUPERUSER and NOBYPASSRLS.
15. Audit records are append-only at the database boundary.
16. Broker-specific technology does not enter the Transaction Kernel.

## Persistent records

### IdempotencyRecord

Required fields:

- id
- tenant_id
- operation
- idempotency_key
- request_hash
- status
- transaction_id
- result_reference
- response_status
- response_payload
- created_at
- completed_at
- expires_at

Unique key:

`(tenant_id, operation, idempotency_key)`

### OutboxMessage

Required fields:

- id / message_id
- tenant_id
- transaction_id
- actor_id
- type
- schema_version
- source
- occurred_at
- available_at
- published_at
- correlation_id
- causation_id
- aggregate_type
- aggregate_id
- aggregate_version
- payload
- payload_hash
- attempt_count
- lease_owner
- lease_until
- last_error

### InboxMessage

Required fields:

- id
- tenant_id
- consumer_name
- message_id
- message_type
- correlation_id
- causation_id
- payload_hash
- received_at
- processed_at

Unique key:

`(tenant_id, consumer_name, message_id)`

### AuditRecord

Required fields:

- id
- tenant_id
- transaction_id
- actor_id
- correlation_id
- capability
- action
- resource_type
- resource_id
- outcome
- occurred_at
- details

AuditRecord is append-only. Runtime UPDATE and DELETE are forbidden.

## Delivery semantics

Producer:

`business state + audit + outbox -> COMMIT -> asynchronous publish`

Consumer:

`inbox registration + business effect + audit/outbox -> COMMIT`

A publisher crash after external publish and before marking the outbox message as published may cause duplicate delivery. Consumers MUST therefore be idempotent.

## Concurrency

Standard aggregate writes use:

`UPDATE ... SET ..., version = version + 1 WHERE id = :id AND version = :expected_version`

Zero affected rows means `ConcurrencyConflict`.

Retries are allowed only for operations proven safe/idempotent.

## Out of scope

- Saga / Process Manager
- Reconciliation Engine
- generalized scheduler
- production broker selection
- administrative DLQ/quarantine UI
- cryptographic EvidenceRecord
- hash chaining / digital signatures
- full OpenTelemetry implementation
- break-glass
- business-domain aggregates

## Certification

P0-I3 is not certifiable until C-I3-01 through C-I3-20 are PASS on the certified Python 3.12 environment and the PostgreSQL 12.22 / 18 matrix.
