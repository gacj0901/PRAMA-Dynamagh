# O_EPISTEMIC ↔ PRAMA partial structural correspondence v0.1

Status: experimental, offline, reference-only. This document freezes the
partial correspondence demonstrated through E2-C8. It does not add runtime
authority, persistence, Decision inputs, or production behavior.

## Semantic classes

### DOMAIN_ESTABLISHED_OBSERVABLE

`OMEGA_EPI_EXPERIMENTAL_V0_1`:

```text
omega_k = |R_(k-1) Δ R_k| / |R_(k-1) ∪ R_k|
```

with empty/empty equal to zero. It means requirement-local,
artifact-attributed fractional turnover of the canonical semantic relational
surface.

### DOMAIN_ESTABLISHED_CAUSAL_BASELINE

Both alternatives are established and neither is preferred:

- `EXPECTED_PV_V0_1`: `expected_k = omega_(k-1)`.
- `EXPECTED_ECM_V0_1`: arithmetic mean of all strictly prior omega values in
  the exact causal population.

The population is fixed by `trajectory_lineage_id`, `target_id`,
`requirement_id`, and `semantic_version_tuple`. There is no cross-target,
cross-requirement, cross-lineage, or cross-version pooling.

Adapter identities remain separate:

- `O_EPI_TURNOVER_PV_V0_1`
- `O_EPI_TURNOVER_ECM_V0_1`

### KERNEL_DEFINED_DOMAIN_INTERPRETABLE_DERIVED

PRAMA defines:

```text
Delta_k = |omega_k - expected_k| / (expected_k + 1)
```

Its only permitted domain interpretation here is normalized discrepancy
between observed relational turnover and the selected causal turnover
baseline. Delta is not independently discovered O_EPISTEMIC semantics.

### DOMAIN_ADAPTER_SEMANTICS_ESTABLISHED

`h = 1` means one E1 semantic evaluation event per stream bin. It does not
represent physical time, a magnitude, or a calibrated dynamical parameter.

### FORMAL_KERNEL_SEMANTICS_ONLY

The following retain only their certified mathematical meanings:

`delta_tilde`, `Xi`, `e`, `A`, `lambda`, `Theta`, `M`, and `G`.

## Demonstrated path

```text
Target / Requirement / Evidence
        ↓
E1 relational state G_k
        ↓
E2-B trajectory G_(k-1) → G_k
        ↓
RELATION_SET_DYNAMICS
        ↓
φ_distance
        ↓
OMEGA_EPI_EXPERIMENTAL_V0_1
        ↓
PV or ECM causal baseline
        ↓
PRAMA Protokol v0.3.0
        ↓
REFERENCE_GAMMA_ONLY
```

The domain-justified boundary ends at omega and the selected causal baseline.
Delta is a Kernel-defined, domain-interpretable derived coordinate. From
`delta_tilde` onward the correspondence is formal-only.

## Frozen contract

`O_EPI_PRAMA_PARTIAL_CORRESPONDENCE_V0_1` binds:

- `OMEGA_EPI_EXPERIMENTAL_V0_1`;
- `EXPECTED_PV_V0_1` and `EXPECTED_ECM_V0_1`;
- `O_EPI_TURNOVER_PV_V0_1` and `O_EPI_TURNOVER_ECM_V0_1`;
- exact causal population and lineage/version isolation;
- explicit E2-B event-index semantics;
- canonical exact-value to IEEE-754 float64 adapter conversion;
- certified PRAMA Protokol v0.3.0;
- certified default KernelConfig values for reference projection only;
- the semantic class of every coordinate;
- the absence of Decision authority.

The exact Fraction source value is retained beside the float64 adapter value.
No clipping, application rounding, rescaling, or renormalization is part of
this contract.

Certified defaults are not epistemically calibrated:

```text
h=1.0, tau=336.0, theta_scale=2.0,
lambda_0=1.0, lambda_min=0.1, lambda_max=1.0,
kappa_v3=9.957514604354753e-7, g_smooth=24, delta_ref=1.0
```

`sigma_op` has no domain semantics; the reference fallback is mechanical only.
`u_lambda=0` means only that no external recovery input is supplied.

## Negative findings

The following are frozen findings, not missing TODO values:

- PV versus ECM preference is unresolved.
- Domain support threshold is not established.
- Physical-time interpretation is not established.
- Multi-stream semantics are not established.
- `delta_ref`, `tau`, threshold, lambda, recovery, smoothing, and `sigma_op`
  semantics are not established.
- Full KernelV3 domain correspondence is not established.
- No Decision semantics are established.

## Default partial dynamic inactivity

The correct term is `DEFAULT_PARTIAL_DYNAMIC_INACTIVITY`.

Under the frozen omega bounds and certified defaults, `delta`, `delta_tilde`,
`Xi`, `M`, and `G` may vary, while `e=0`, `A=0`, `lambda=1`, and `Theta=2`.
This means the domain contract does not reach the default activation region; it
does not indicate failure of O_EPISTEMIC or PRAMA.

## Separation and authority boundary

This correspondence belongs only to O_EPISTEMIC. It does not consume or
reinterpret O_EVIDENCE_PROVENANCE Gamma, miner reputation, source reliability,
O_AGENT trajectory, G13 policy state, or Decision outcomes.

O_EPISTEMIC observation is distinct from PRAMA reference characterization and
from the Dynamagh Decision. No coordinate maps to `PERMIT`, `REVIEW`, `BLOCK`,
`CONTINUE`, `THROTTLE`, or `HALT`. E3 remains future work.

## Evidence ledger

- E1: domain relational contract.
- E1-P: controlled perturbation exposed and corrected a temporal mismatch.
- E2-B: causal, versioned trajectory.
- E2-C1.5: `RELATION_SET_DYNAMICS` identified as primitive.
- E2-C2: 14/14 primitive perturbations passed.
- E2-C-P: 28/28 required cases passed.
- E2-C4-P: PV and ECM causal baselines passed.
- E2-C5: input and scale audit passed.
- E2-C6: first offline KernelV3 reference projection passed.
- E2-C7: partial semantic correspondence audit passed.

## Falsifiability and versioning

Version v0.1 is invalidated if:

- omega no longer satisfies its frozen perturbation properties;
- an expectation consumes current or future information;
- causal history leaks across lineage or version boundaries;
- canonical relational identity changes semantically;
- reference replay ceases to be deterministic;
- a claimed domain mapping requires an unsupported parameter; or
- Decision authority is introduced without a separate E3 contract.

Any correction creates a new semantic version. V0.1 must not be silently
rewritten.

## Explicit nonclaims

This contract does not claim truth, knowledge, confidence, viability,
sufficiency, deterioration, improvement, probability, admissibility,
forecasting, intervention, or Decision authority.
