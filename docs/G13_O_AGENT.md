# G13-C: O_AGENT v0

`O_AGENT` is a read-only, deterministic projection of persisted autonomous-domain
artifacts. It is built by `app.agents.observation.build_o_agent_stream` for one
`AgentIdentity`, optionally bounded by timestamps or an `AutonomyRun`.

Each observation contains:

- `schema_version: o-agent-v0`;
- stable source kind/id and complete source lineage;
- exact `AgentIdentity` and M2M/AUTONOMOUS surface attribution;
- ordered timestamp/sequence information;
- action, run, acquisition, latency, attempts, recurrence, concurrency, cost,
  budget-pressure, failure/recovery, and completion facts when persisted;
- explicit `missing_data` codes for unavailable telemetry;
- canonical JSON bytes and a deterministic content hash.

Local Decision state is recorded with `LOCAL_DECISION_ONLY`. O_AGENT does not
compute trajectory viability, semantic truth, thresholds, or CONTINUE/THROTTLE/
REVIEW/HALT decisions. It does not block execution, call Telegraph, access the
Gateway or signer, or create new payment authority.
