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

El scheduler respeta el estado persistente de la identidad. `HALTED` y
`REVIEW_REQUIRED` no vuelven a despertar en el siguiente cron. La señal de
Titular Check se incorpora a O_AGENT/K-Mem/G13 como dimensión longitudinal,
sin alterar el Decision Gate epistemológico.

La activación de producción requiere configurar explícitamente el flag global,
el allowlist de canary y los perfiles. Esta revisión no realiza adquisiciones
Telegraph ni tráfico pagado.
