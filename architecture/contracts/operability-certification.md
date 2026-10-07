# P0-I4 Operability & Certification - Implementation Contract

Status: IMPLEMENTATION CONTRACT
Version: 1.0
Date: 2026-09-24
Prerequisite tag: `p0-i3-certified`
Prerequisite commit: `24e35dd367fc51c0b0467b7c2327ab810acf455d`

## 1. Objective

P0-I4 closes Phase 0 by making the certified platform foundation observable,
operable, recoverable, reproducible and releasable.

P0-I4 is not the complete future Operations Platform. It implements the
minimum production-grade operability and certification foundation required
before opening Phase 1.

The final gate is a formal Go/No-Go decision for Phase 1.

## 2. Normative scope

Source backlog:

- P0-018 Observability
- P0-020 Control Plane
- P0-021 Tenant Provisioning
- P0-024 Test Platform
- P0-025 Architecture Fitness
- P0-026 CI/CD & Supply Chain
- P0-029 Developer Experience
- P0-030 Phase 0 Certification

Selected P1 scope:

- P0-017 Evidence Foundation
- P0-027 Performance Baseline
- P0-028 Recovery Foundation

P0-I4 MUST also close any residual Phase 0 MUST requirement that is not
already demonstrably certified by P0-I1, P0-I2 or P0-I3.

## 3. Operability architecture

### 3.1 Observability

OpenTelemetry is the vendor-neutral telemetry boundary.

The reference implementation MUST provide:

- structured logs;
- traces;
- metrics;
- correlation propagation;
- OTLP-compatible export;
- a local telemetry collector for certification.

The following execution path MUST be traceable when applicable:

HTTP ingress
-> authentication / policy
-> application command
-> UnitOfWork
-> PostgreSQL
-> Audit
-> Outbox
-> publisher
-> consumer
-> Inbox
-> persistent side effect.

Telemetry MUST NOT contain:

- bearer tokens;
- client secrets;
- private keys;
- database passwords;
- full sensitive request payloads unless explicitly allowed by policy.

### 3.2 Control Plane

The Phase 0 Control Plane is an internal administrative plane.

It MUST be separated logically from normal tenant business APIs and MUST use
dedicated capabilities.

Minimum operations:

- tenant.provision
- tenant.activate
- tenant.suspend
- platform.health.inspect
- configuration.read
- audit.search.basic
- outbox.inspect
- outbox.retry

Every Control Plane operation MUST be:

- authenticated;
- explicitly authorized;
- correlated;
- durably audited.

No valid JWT alone authorizes a Control Plane operation.

### 3.3 Tenant provisioning

Tenant provisioning MUST be an explicit state machine.

Minimum lifecycle:

PROVISIONING
-> ACTIVE

Failure path:

PROVISIONING
-> PROVISIONING_FAILED
-> retry / repair
-> ACTIVE

Provisioning MUST be:

- idempotent;
- resumable;
- safe under retry;
- observable;
- audited.

A partially initialized tenant MUST NEVER be ACTIVE.

Default configuration, security and platform defaults MUST be installed
before activation.

### 3.4 Evidence Foundation

EvidenceRecord is distinct from AuditRecord.

Evidence MUST bind, where applicable:

- evidence_id;
- tenant_id;
- transaction_id;
- actor_id;
- correlation_id;
- capability;
- resource reference;
- request_hash;
- result_hash;
- created_at;
- key_id;
- signature metadata.

The canonical request/result hashes MUST be deterministic.

The cryptographic implementation MUST use standard maintained primitives
behind a replaceable port. No custom cryptographic algorithm is permitted.

The reference adapter SHOULD demonstrate signature creation and verification
with key identification and tamper detection.

Trusted timestamping, external HSM/KMS integration and hash-chain ledgers are
not required for the Phase 0 gate.

### 3.5 Break-glass guard

As a selected premium Control Plane hardening, an emergency elevation contract
MUST exist before Phase 0 closure.

A break-glass grant MUST have:

- explicit actor;
- explicit reason;
- explicit scope;
- explicit capability set;
- activation time;
- expiration time;
- elevated authentication assurance evidence;
- durable audit;
- EvidenceRecord linkage.

A break-glass grant MUST NOT create a permanent universal super-administrator.

The break-glass grant lifecycle MUST support explicit issuance, suspension,
resumption and revocation.

Every break-glass lifecycle mutation MUST:

- require the dedicated `platform.break-glass.manage` capability;
- require direct authorization and reject authorization obtained through a
  break-glass elevation;
- remain tenant-scoped;
- enforce optimistic concurrency against the expected grant version and source
  status where applicable;
- commit the state mutation, AuditRecord and linked EvidenceRecord atomically.

A suspended grant MUST NOT be resumed outside its validity window.

Revocation MUST be terminal.

A break-glass path MUST NOT bypass tenant isolation, evidence generation or
audit.

A complete administrative UI and organizational approval workflow are outside
Phase 0.

### 3.6 Health model

Startup, liveness and readiness remain distinct.

Public health output MUST NOT expose:

- credentials;
- connection strings;
- host topology;
- internal exception details;
- tenant data;
- provider secrets.

Privileged Control Plane diagnostics MAY expose additional non-secret
operational state under explicit authorization.

### 3.7 Test Platform

Reusable certification fixtures MUST exist for:

- Tenant;
- Actor;
- capability/policy;
- execution context;
- PostgreSQL;
- identity provider;
- reference messaging transport;
- telemetry collector.

Reusable assertions SHOULD cover:

- audit;
- evidence;
- outbox;
- inbox;
- telemetry correlation;
- cross-tenant denial.

C-I4-13 certification evidence is implemented by the reusable
`tests/test_platform/` package and registered globally through
`tests/conftest.py`:

- `fixtures.py` provides deterministic Tenant, Actor, capability/policy and
  execution-context fixtures;
- `identity.py` provides an in-process reference OIDC provider exercising the
  real `OidcTokenAuthenticator`;
- `postgres.py` provides a migrated PostgreSQL certification fixture, proven
  on PostgreSQL 12.22 and PostgreSQL 18;
- `messaging.py` provides the reference in-memory messaging transport;
- `telemetry.py` provides an in-memory collector backed by the real
  `ObservabilityRuntime`;
- `assertions.py` provides reusable audit, evidence, outbox, inbox and
  cross-tenant denial assertions;
- `telemetry_assertions.py` provides reusable distributed-trace correlation
  assertions.

The certification tests prove the Test Platform through real runtime
boundaries where applicable: PostgreSQL migrations and RLS, the transactional
UoW, Audit/Evidence persistence, Outbox/Inbox persistence, OIDC token
validation and OpenTelemetry collection.

### 3.8 CI/CD and supply chain

The release pipeline MUST gate, at minimum:

build
-> lint / formatting
-> type checking
-> architecture fitness
-> unit tests
-> security scans
-> integration tests
-> migration tests
-> contract tests
-> immutable artifact build
-> SBOM generation
-> artifact signing / attestation
-> verification
-> smoke / certification subset.

A deployable artifact MUST be identifiable by version and commit.

The SBOM MUST be tied to the release artifact.

### 3.9 Developer Experience

A versioned local procedure MUST support:

- environment bootstrap;
- PostgreSQL;
- reference IdP;
- reference messaging transport or equivalent;
- telemetry collector;
- deterministic tenant/actor seed;
- reset/rebuild;
- tests;
- local host start.

No real production secret is required locally.

### 3.10 Performance baseline

P0-I4 establishes a baseline, not a final production capacity promise.

The harness MUST record:

- latency;
- throughput;
- errors;
- concurrency;
- tenant mix;
- environment metadata.

A simple noisy-neighbor scenario MUST verify that load does not defeat tenant
isolation or explicit admission/limit controls available in Phase 0.

### 3.11 Recovery foundation

The certification environment MUST demonstrate:

- database backup;
- database restore;
- schema/migration consistency after restore;
- Outbox persistence during transport outage;
- publication after transport recovery.

Recovery procedures MUST be versioned in a runbook.

### 3.12 Phase 0 certification resource

`TestResource` is a technical certification aggregate only.

It MUST NOT enter the Universal Business Model.

The certification flow is:

Actor authentication
-> tenant resolution
-> capability authorization
-> CreateTestResource
-> idempotency
-> UnitOfWork
-> TestResource state
-> Audit
-> Evidence where required
-> Outbox
-> commit
-> reference transport
-> consumer
-> Inbox
-> persistent side effect
-> telemetry correlation.

## 4. Core invariants

1. P0-I3 transaction guarantees remain unchanged.
2. Telemetry is vendor-neutral at the platform boundary.
3. correlation_id links ingress, transaction, audit and messages.
4. trace context is propagated across asynchronous boundaries where supported.
5. telemetry never intentionally records secrets.
6. Control Plane authorization is explicit and default-deny.
7. all Control Plane mutations are durably audited.
8. tenant provisioning is idempotent and resumable.
9. a partially provisioned tenant can never become ACTIVE.
10. Control Plane diagnostics never bypass RLS or tenant policy.
11. EvidenceRecord is distinct from operational AuditRecord.
12. evidence hashes are deterministic and bound to the represented operation.
13. break-glass is explicit, scoped and time-bounded.
14. break-glass never creates an untracked universal privilege.
15. health endpoints expose only the minimum required information.
16. release artifacts are immutable and attributable to source commit.
17. security and architecture gates remain blocking.
18. recovery tests demonstrate absence of transaction loss or partial state.
19. TestResource remains certification-only.
20. Phase 1 MUST NOT open while a Phase 0 MUST requirement lacks evidence or an
    explicitly approved ADR deviation.

## 5. Certification matrix

| ID | Criterion |
|---|---|
| C-I4-01 | Structured telemetry propagates correlation/trace context from ingress through application, DB/transaction and asynchronous messaging. |
| C-I4-02 | Telemetry redaction tests prove tokens, secrets and protected configuration are not emitted. |
| C-I4-03 | Runtime metrics expose command/error/latency, DB pool, Outbox and Inbox operational signals. |
| C-I4-04 | Startup, liveness and readiness remain distinct and public health output contains no sensitive infrastructure detail. |
| C-I4-05 | Every Control Plane operation requires a dedicated explicit capability and produces durable audit. |
| C-I4-06 | Tenant activate/suspend transitions enforce lifecycle rules and are correlated/audited. |
| C-I4-07 | Outbox inspect/retry is safe, non-destructive, fenced where required and fully audited. |
| C-I4-08 | Effective configuration, health inspection and basic audit search expose no secret and respect authorization boundaries. |
| C-I4-09 | Tenant provisioning is idempotent and resumes correctly after injected mid-workflow failure. |
| C-I4-10 | A partially provisioned tenant never becomes ACTIVE and failed provisioning remains repairable. |
| C-I4-11 | EvidenceRecord binds request/result hashes, transaction, actor and correlation; reference signing verifies and tampering is detected. |
| C-I4-12 | Break-glass grants require elevated assurance, reason, scope and expiry; issuance, suspension, resumption and revocation are directly authorized, tenant-scoped, concurrency-safe and atomically audited/evidenced; resumption respects validity, revocation is terminal and break-glass elevation cannot administer the lifecycle. |
| C-I4-13 | Reusable Test Platform fixtures/assertions support tenant, identity, policy, DB, messaging and telemetry certification scenarios. |
| C-I4-14 | Architecture fitness and residual Phase 0 MUST checks pass with no unapproved violation. |
| C-I4-15 | CI produces an immutable commit-addressable artifact, SBOM and verifiable signature/attestation after all quality/security gates pass. |
| C-I4-16 | Versioned local bootstrap/seed/reset procedure reproduces the complete Phase 0 certification environment. |
| C-I4-17 | Performance harness records a reproducible baseline and noisy-neighbor test does not defeat isolation/control boundaries. |
| C-I4-18 | Database backup/restore and transport outage/recovery complete successfully without lost committed transaction state. |
| C-I4-19 | Complete TestResource certification scenario passes: cross-tenant denial, idempotent replay, hash conflict, optimistic concurrency conflict, policy DENY, duplicate delivery and one persistent effect. |
| C-I4-20 | DB/transaction failure and transport failure injection, end-to-end trace/audit/evidence correlation, full regression, security, migration and supply-chain gates are green and the formal Phase 0 Go/No-Go record is produced. |

## 6. PostgreSQL compatibility

Any P0-I4 persistent schema MUST be certified on:

- PostgreSQL 12.22 compatibility floor;
- PostgreSQL 18 reference.

Migration certification MUST include:

- fresh install;
- `p0-i3-certified` -> P0-I4 upgrade;
- preservation of representative P0-I3 data.

## 7. Reference transport and telemetry

Kernel/application contracts MUST remain vendor-neutral.

A concrete local reference transport and OpenTelemetry stack MAY be introduced
for certification, but business and transaction kernels MUST NOT depend on
their SDKs.

Reference infrastructure dependencies MUST remain replaceable adapters.

C-I4-14 certification evidence demonstrates that architecture fitness and
residual inherited Phase 0 MUST requirements are green with no approved
deviation required:

- all architecture fitness tests pass;
- all four Import Linter dependency contracts are kept with zero broken
  contracts;
- runtime PostgreSQL role/RLS invariants are covered by automated tests;
- PostgreSQL 12.22 / PostgreSQL 18 compatibility requirements are covered by
  migration and runtime compatibility tests;
- transaction consumer idempotence is covered by Inbox effectively-once and
  transaction-kernel tests;
- no approved ADR deviation is required for the certified residual checks.

## 8. Explicitly deferred

The following are not required to close Phase 0:

- full administrative web UI;
- full SaaS billing/metering platform;
- generalized quota engine;
- generalized Saga / Process Manager;
- generalized reconciliation and repair framework;
- generalized DLQ administration;
- production multi-region HA;
- final capacity/SLO guarantees;
- production HSM/KMS integration;
- trusted timestamp authority;
- cryptographic audit hash chain;
- service-mesh-wide mTLS/workload identity;
- external OPA/Cedar policy engine;
- SCIM provisioning;
- production-grade scheduler.

These items require their own later capability increments unless a P0-I4
implementation dependency makes a minimal adapter necessary.

## 9. Implementation sequence

- I4.0 Contract and residual Phase 0 gap inventory
- I4.1 Observability foundation
- I4.2 Evidence foundation and break-glass guard
- I4.3 Control Plane operations
- I4.4 Tenant provisioning
- I4.5 Test Platform and architecture fitness completion
- I4.6 CI/CD, immutable artifact and supply-chain attestation
- I4.7 Developer Experience / local certification stack
- I4.8 Performance and recovery foundation
- I4.9 TestResource full Phase 0 E2E certification
- I4.10 Final quality, security and Phase 0 Go/No-Go seal

## 10. Immediate NO-GO conditions

P0-I4 cannot be certified if any of the following remains:

- cross-tenant exposure;
- Control Plane operation without explicit authorization;
- Control Plane mutation without durable audit;
- secret/token leakage in telemetry;
- partially provisioned tenant marked ACTIVE;
- unaudited or non-expiring break-glass privilege;
- break-glass lifecycle administration authorized through break-glass
  elevation or committed without linked AuditRecord/EvidenceRecord;
- Evidence verification accepting tampered content;
- loss of committed Outbox state during transport outage;
- restore that cannot recover a migration-consistent database;
- unsigned/unidentified release artifact where attestation is configured;
- Phase 0 MUST requirement without evidence or approved ADR deviation;
- incomplete or non-automated P0-ARCH-062 certification scenario.
