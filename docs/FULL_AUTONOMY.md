# Full Autonomy Deployment v1

PRAMA-Dynamagh ejecuta autonomía delegada únicamente cuando existe una
`AgentAuthorityProfile` vigente, una identidad M2M inequívoca y el canary
`FULL_AUTONOMY_ENABLED` está activo para esa identidad.

El flujo de una acción externa es:

```text
authenticated context
  -> exactamente un AgentIdentity
  -> AuthorityProfile vigente
  -> G12 PERMIT (presupuesto delegado)
  -> O_AGENT longitudinal (todos los runs de la identidad)
  -> G13 binding authority
  -> ExecutionPermit de una sola acción
  -> Gateway / Telegraph
```

G13 es vinculante en el punto de acción:

```text
CONTINUE  -> ejecutar
THROTTLE  -> ejecutar sólo con restricciones satisfechas
REVIEW    -> bloquear; no hay red ni pago
HALT      -> bloquear; no hay red ni pago
```

Cada `ExecutionPermit` identifica principal, agente, mandato, acción, G12,
G13, restricciones y hash de autoridad. Se consume una sola vez. Los perfiles
son inmutables; una modificación del principal o de sus límites crea una nueva
versión. Los eventos de auditoría `append_only=true` rechazan UPDATE/DELETE en
persistencia.

## Canonical temporal semantics for `ExecutionPermit`

`ExecutionPermit` uses a **HYBRID** authority model. Issuance records immutable
facts and the authority state observed at `t0`; it does not freeze authority
that can later be revoked or changed.

At issuance (`t0`), record and integrity-bind the permit's immutable facts:
principal, identity, mandate, action identifier and kind, exact payload/query,
execution target/provider/adapter, and the authorized economic envelope.
Immediately before dispatch, the runtime reaches an **Execution Commitment
Point** in one database transaction. It checks action integrity and equality,
fresh revocable authority, permit expiry when configured, and single-use
availability; consumes the permit; and records an append-only
`EXECUTION_DISPATCH_COMMITTED` event containing the action-envelope and
authority hashes. The event and `consumed_at` transition commit atomically.

`consumed_at` therefore means the exact bound action crossed the Execution
Commitment Point and is authorized for one best-effort dispatch. It does not
prove that the provider received the request or returned a result. Authority
changes committed before the point prevent commitment. Changes committed
after it do not retroactively revoke that one committed execution; every later
action requires a new permit and fresh authority.

Canonical invariants:

- `NO_DISPATCH_COMMIT_WITH_STALE_AUTHORITY`
- `EXECUTION_PERMIT_ACTION_BINDING`
- `EXECUTION_PERMIT_SINGLE_USE`
- `POST_COMMIT_AUTHORITY_CHANGES_ARE_NON_RETROACTIVE`

Operationally, no execution may cross the commitment point if any revocable
authority required for the action is invalid at the time of that atomic
commitment. A later authority change cannot revoke that single execution.

This contract applies to `origin == AUTONOMOUS`. M2M is not included and is
unaffected by this permit contract. It does not create another workflow engine,
change PRAMAgraph, or add a second Decision Gate. The separate bootstrap
authority's existing consumption checks remain in force.

### Current implementation status

The autonomous worker now stores a canonical action envelope in the existing
permit `constraints` JSONB and includes it in `authority_hash`. The envelope
binds the exact query/request hash, mandate, identity, action id/kind, adapter
provider and mechanism, adapter kind, a fingerprint of the execution target,
authorized amount, the G12 reservation facts, and the AgentIdentity autonomy
state observed at issuance. Consumption recomputes the permit hash, compares
the requested action with the bound envelope, and rejects legacy permits that
have no such envelope.

Immediately before dispatch, the worker locks and reloads the permit, mandate,
task, identity, spend reservation and effective profile; rechecks profile and
G12 limits; recomputes G13 and the existing authority composition; then
consumes the permit and records the dispatch commitment in that same
transaction. Bootstrap authority retains its existing consumption-time
validation and is consumed in the same transaction when applicable. The
worker commits before calling the adapter and does not hold a database
transaction open over network I/O.

The commitment transaction uses this lock order:

```text
ExecutionPermit -> Mandate -> AcquisitionTask -> AgentIdentity
  -> PublicManualSpendReservation -> AuthorityProfile
  -> UserCreditAccount -> BootstrapAuthority
```

G13 enforcement writes the derived autonomy state on the locked
`AgentIdentity` row. Profile lifecycle changes lock the profile row; profile
replacement also locks the identity before the profile. G12 release and
settlement lock the reservation row. These shared rows order the existing
authority mutation paths against commitment; those paths must continue using
the same row locks.

The database commitment and external request cannot be atomic. After
commitment, dispatch is best-effort and an adapter rejection or timeout is an
authorized dispatch failure, not an authority rejection. A process crash
after the commitment event but before `adapter.acquire()` leaves a consumed
permit and running task; existing recovery cannot prove whether the external
call began, so it cannot safely replay or recover that dispatch. This remains
a delivery/recovery concern outside this ticket. PostgreSQL replay and
authority-ordering tests pass against a local isolated database; see
[`TICKET_EXECUTION_PERMIT_AUTHORITY.md`](TICKET_EXECUTION_PERMIT_AUTHORITY.md)
for validation limits.

Legacy permits fail closed. `expires_at` remains nullable and issuance does
not assign a TTL; `TTL_POLICY: UNDEFINED`. A null TTL does not waive fresh
authority or action-binding checks.

`TTL_POLICY: UNDEFINED`. No numeric TTL is established here. Fresh authority
and action-binding checks at `t1` are required regardless of TTL; choosing a
TTL remains a separate lifecycle/replay policy decision.

El scheduler respeta el estado persistente de la identidad. `HALTED` y
`REVIEW_REQUIRED` no vuelven a despertar en el siguiente cron. La señal de
Titular Check se incorpora a O_AGENT/K-Mem/G13 como dimensión longitudinal,
sin alterar el Decision Gate epistemológico.

La activación de producción requiere configurar explícitamente el flag global,
el allowlist de canary y los perfiles. Esta revisión no realiza adquisiciones
Telegraph ni tráfico pagado.
