# TICKET_EXECUTION_PERMIT_AUTHORITY

Status: IMPLEMENTED — the commitment semantics and isolated PostgreSQL race
tests are implemented and pass. Existing unrelated environment-limited tests
are classified below.

## Sole question

Can an `ExecutionPermit` that was valid at `t0` cause an external side effect
at `t1` after the authority that justified it has changed?

The canonical answer required by
[`FULL_AUTONOMY.md`](FULL_AUTONOMY.md) is HYBRID: issuance binds immutable
action facts and records the authority observed at `t0`; immediately before
the external side effect, the system must validate fresh revocable authority
and prove that the actual action is still the bound action.

## Scope

Autonomous acquisition only (`Mandate.origin == AUTONOMOUS`). M2M is out of
scope and unaffected. Preserve the existing authority composition and
Decision Gate boundaries. Do not create another workflow engine, rework
PRAMAgraph, or add a second Decision Gate.

## Required cases

Prove that a stale, invalid, expired, consumed, or action-mismatched permit
cannot cause an external side effect. Cover:

- mandate revocation/status change, if an applicable revocation transition is
  available;
- G12 reservation and budget authority changing after issuance;
- G13 `PERMIT -> THROTTLE`, `PERMIT -> REVIEW`, and `PERMIT -> HALT`;
- effective AuthorityProfile lifecycle/version/status change;
- agent identity autonomy state change;
- payload/query mutation;
- execution target, provider, or adapter mutation;
- economic envelope mutation, including amount and applicable spend limits;
- expiration / TTL policy (`TTL_POLICY` is currently `UNDEFINED`; do not
  invent a numeric value in this ticket);
- single-use semantics, including concurrent consumption;
- replay and idempotency behavior;
- permit consumption ordering and failure around the external side effect;
- binding and revalidation of the authority state used to authorize the
  action.

An authority transition that does not currently exist in code must be recorded
as not applicable or as a prerequisite, rather than represented as an
implemented revocation path.

## Pre-implementation code evidence (audit baseline)

`app/workers/acquisition.py` runs the binding pre-next-action authority check,
issues and commits the permit, consumes and commits it, then invokes the
acquisition adapter. In `app/authority/delegated.py`, issuance checks the
current profile, identity autonomy state, G12 reservation evidence, and the
provided G13 result. Consumption locks the permit row and checks only
existence, prior consumption, and expiry when `expires_at` is non-null before
marking it consumed. It does not re-resolve the profile, G12, G13, identity,
or mandate authority.

The issuance hash currently covers principal, identity, mandate, action id and
kind, profile id, G12/G13 results, decision id, and constraints. It does not
include the actual query/payload, execution target/provider/adapter, or
economic amount, and is not recomputed at consumption. Issuance leaves
`expires_at` unset. A unique action id and locked consumed-at transition
provide direct replay protection, but do not satisfy fresh-authority or
action-binding requirements. PostgreSQL concurrent-consumption behavior has
not been established by a dedicated race test.

The bootstrap grant path performs its own consumption-time scope, status,
remaining-action, and spend checks. Preserve that specialized behavior and
assess only any remaining interaction with the canonical permit contract.

## Implementation progress

The runtime builds and hashes an action envelope in the existing `constraints`
JSONB, checks that envelope and permit hash while holding the one-shot permit
row lock, reloads mandate/task/identity/reservation/profile, rechecks G12 and
the existing G13 authority composition, then consumes the permit and records
`EXECUTION_DISPATCH_COMMITTED` in the same transaction. The existing
`consumed_at` field plus the immutable action envelope/hash and append-only
commitment event represent the exact action authorized for dispatch; no schema
change is needed. Missing action envelopes fail closed, so legacy permits
cannot bypass the new binding.

The commitment transaction uses this lock order:
`ExecutionPermit -> Mandate -> AcquisitionTask -> AgentIdentity ->
PublicManualSpendReservation -> AuthorityProfile -> UserCreditAccount ->
BootstrapAuthority`. Identity G13 state changes, profile lifecycle operations,
and G12 reservation mutations serialize through those existing rows. A
mutation committed before commitment is observed and rejected; a mutation
committed after commitment does not revoke that single execution. Provider I/O
starts after commit, with no open DB transaction.

If the process crashes after commitment and before calling the adapter, the
permit remains consumed and the task remains running. Existing recovery cannot
prove whether dispatch began, so it cannot safely retry; this is not
automatically recoverable and remains a separate delivery/recovery concern.
An adapter or provider failure after commitment is an authorized dispatch
failure, distinct from an authority rejection before commitment.

PostgreSQL concurrency and authority-ordering tests use an isolated schema
and independent sessions. All seven tests pass against local PostgreSQL:
one concurrent consumer race plus before/after races for G13 HALT, Authority
Profile revocation, and G12 reservation release. No provider adapter is called
by these tests. DB commitment and provider I/O are not atomic.

## Required design and acceptance evidence

Before implementation, specify the exact `t1` validation order and fail-closed
behavior. The smallest candidate design should reuse the existing permit
constraints and canonical `authority_hash` material where sufficient, binding
the exact action payload/query, target/provider/adapter, action kind/id, and
economic envelope. Recompute or compare those bindings against the action
actually about to be sent. Decide explicitly whether storage/schema changes
are needed; do not assume a migration is needed or add one without evidence.

Required acceptance tests for closing this ticket:

1. G12 reservation revoked/changed after issuance prevents adapter dispatch.
2. Each G13 transition from `PERMIT` to `THROTTLE`, `REVIEW`, and `HALT` is
   re-evaluated and obeys its current constraints.
3. Profile lifecycle/version and identity autonomy changes prevent dispatch
   when current authority no longer permits the action.
4. Payload/query, target/provider/adapter, or economic-envelope mutation is
   rejected before dispatch.
5. Valid unchanged authority and action permit exactly one dispatch.
6. Expired, consumed, and replayed permits cannot dispatch; configured TTL
   behavior is deterministic. TTL value/policy must be separately decided.
7. Concurrent consumption has a PostgreSQL integration test proving at most
   one successful consumer and no duplicate external side effect.
8. Idempotent retries preserve the same lineage and do not repeat a consumed
   side effect; failure between permit consumption and the external response
   is explicitly characterized.
9. Mandate revocation behavior is tested if a real revocation state/transition
   exists; otherwise the test/design records that prerequisite rather than
   inventing one.
10. M2M paths remain unchanged and do not begin using autonomous
    `ExecutionPermit` checks.

## Validation evidence to date

- `tests/unit/test_execution_permit_authority.py` plus the caller/signature
  contract tests: 29 passed.
- Authority/profile/runtime and worker-focused regression selection: 94
  passed; `compileall`: passed.
- Latest combined authority/G13/M2M regression selection: 145 passed, 1
  failed. The sole failure is the PostgreSQL-backed M2M auth test, which could
  not resolve the configured `postgres` hostname; no assertion failure in the
  permit/G12/G13 unit tests occurred.
- After the commitment-event change, the same selection excluding that
  database-backed case: 145 passed, 1 deselected. The dedicated permit and
  signature tests: 29 passed; `compileall`: passed.
- The isolated PostgreSQL selection passed all seven cases: one concurrent
  replay race and six before/after authority-ordering cases for G13 HALT,
  Authority Profile revocation, and G12 reservation release. The first run
  against the existing local database exposed an unrelated stale fixture FK;
  a fresh local test database, migrated to head, avoided that data and passed.
- M2M unit selection without its PostgreSQL-backed auth case: 3 passed, 1
  deselected.
- Full unit suite (before this follow-up): 390 passed, 2 failed, 13 errors.
  The two failures require PostgreSQL at hostname `postgres`, which is not
  resolvable from this host. Re-running `tests/unit/test_x402_public.py` gave
  4 passed and the same 13 setup errors: SQLite cannot open its file in the
  fixture's repository-local `.x402-test-*` directory, and `TemporaryDirectory`
  cleanup raises `PermissionError: [WinError 5] Acceso denegado` on those paths.
  The pytest cache path has the same access-denied warning. This establishes a
  local filesystem-permission blocker, not an x402 runtime regression.
- No tests made external requests; no payment or deployment was attempted.

The authority commitment acceptance criteria are met. The full backend suite
is not globally green because unrelated existing tests depend on an unavailable
service hostname or repository-local temporary-file permissions; those
failures are classified above and were not changed by this ticket. The
post-commit/pre-dispatch crash remains unrecoverable automatically and belongs
to a separate delivery/recovery concern, not authority freshness.

## Invariants

- `NO_DISPATCH_COMMIT_WITH_STALE_AUTHORITY`
- `EXECUTION_PERMIT_ACTION_BINDING`
- `EXECUTION_PERMIT_SINGLE_USE`
- `POST_COMMIT_AUTHORITY_CHANGES_ARE_NON_RETROACTIVE`

## Non-goals

- No change to M2M authorization, inbound payment, or seller behavior.
- No changes to Telegraph intent handling, G12/G13 policy semantics, PRAMAgraph,
  or the epistemic Decision Gate.
- No numeric TTL assumption, second gate, or generic workflow engine.
- No implementation in the ticket's documentation-only creation phase.

## Canonical closure

```yaml
EXECUTION_PERMIT_AUTHORITY: IMPLEMENTED
CANON_MODEL: HYBRID

ACTION_BINDING: PASS
AUTHORITY_FRESHNESS: PASS
EXECUTION_COMMITMENT_POINT: ESTABLISHED
SINGLE_USE: PASS
CONCURRENT_REPLAY_PROTECTION: PASS

M2M_AFFECTED: NO

KNOWN_NON_AUTHORITY_GAP:
  POST_COMMIT_PRE_DISPATCH_CRASH_RECOVERY

AUTHORITY_DEFECT_STATUS: CLOSED
```

The post-commit/pre-dispatch crash recovery gap concerns delivery recovery:
after the atomic commitment, the permit is consumed, but existing recovery
cannot prove whether provider I/O began. Track that work separately; it does
not reopen the authority defect addressed here.
