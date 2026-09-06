# G13-A/G13-B: Agent identity and lineage

G13-A introduces the persistent `AgentIdentity` subject. It records the stable
`agent_id`, name, origin, creation time, status, optional autonomy `policy_id`,
and `trajectory_version`. It is an attribution subject, not a signer, wallet,
Gateway credential, or execution authority.

G13-B attaches the subject to newly created autonomous and M2M `Mandate` rows.
The existing `mandate_id` links then carry attribution through Acquisition,
Telegraph, Evidence, StructuralEvaluation, Decision, Ticket, and UsageEvent.
`AutonomyRun` also stores the identity reference directly. Historical links are
backfilled only where an explicit persisted `agent_id` already identifies the
subject; ambiguous rows remain nullable.

M2M identities are additionally bound to a non-reversible SHA-256 context
derived from the authenticated Bearer credential. The submitted `client_id` is
retained as attribution, not treated as authentication. Identity create/read
operations accept only the authenticated external M2M scope; internal autonomy
identities are bootstrapped and are not externally claimable or readable.

This slice does not implement O_AGENT, trajectory observations or evaluations,
ORDSPOC, K-Mem, trajectory policy decisions, CONTINUE/THROTTLE/REVIEW/HALT,
ExecutionPermit, or any new payment/signer/Gateway capability.
