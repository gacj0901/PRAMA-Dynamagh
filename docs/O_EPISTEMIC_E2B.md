# O_EPISTEMIC E2-B trajectory lineage

E2-B is a fixture/test-only categorical transition layer over deterministic E1
relational snapshots. It has no runtime persistence, production execution, or
PRAMA integration.

## Trajectory lineage

`target_id` identifies the stable epistemic target. `trajectory_lineage_id`
identifies one longitudinal reconstruction of that target under a frozen
semantic version tuple:

- target contract version
- E1 observer, contract, algorithm, and canonicalization versions
- E2-B observer, transition-contract, algorithm, and canonicalization versions
- E2-B lineage-identity version

The lineage ID is the deterministic canonical hash of the target ID and this
tuple. Git commits, deployment versions, generated UUIDs, timestamps, and
runtime metadata are excluded. Any change to a trajectory-affecting semantic
version creates a new lineage ex ante; an earlier lineage is never silently
rewritten.

`event_index` is scoped to one lineage and is the only experimental ordering
input. Each lineage starts at `k = 0`; indices are monotonic, immutable, never
reused, and never inferred from timestamps, UUIDs, or database order. The
conceptual requirement-level identity is:

```text
(trajectory_lineage_id, event_index, requirement_id)
```

Transition hashes bind the lineage ID, event index, previous/current E1
snapshot hashes, requirement-level categorical deltas, and semantic versions.
Transition UUIDs and creation times remain incidental and are excluded. No
recursive hash chain is required.

## E1-P empirical validation

During E1-P v0.1, a temporal outside-window perturbation exposed a real mismatch
between the frozen E1 contract and the evaluator implementation. The evaluator
was minimally corrected and the complete E1-P campaign was rerun successfully.
E1-P therefore demonstrated falsification capability against the implementation,
not merely confirmation of expected behavior.
