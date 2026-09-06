from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.pramagraph.evaluation import digest


def observation(sequence: int = 1) -> OAgentObservation:
    payload = {
        "schema_version": "o-agent-v0",
        "observation_id": "o-agent-v0:MANDATE:mandate-1",
        "sequence": sequence,
        "observed_at": "2026-09-05T12:00:00Z",
        "timestamp_source": "created_at",
        "agent_identity_id": "agent-1",
        "agent_origin": "EXTERNAL_API_AGENT",
        "origin_surface": "M2M",
        "source_kind": "MANDATE",
        "source_id": "mandate-1",
        "source_lineage": {"agent_identity_id": "agent-1", "mandate_ids": ["mandate-1"]},
        "facts": {"action_status": "TICKETED", "local_decision_state": "PERMIT", "local_decision_scope": "LOCAL_DECISION_ONLY"},
        "missing_data": ["AUTONOMY_RUN_NOT_LINKED"],
    }
    draft = OAgentObservation(**payload, content_hash="draft")
    canonical_payload = draft.canonical_payload()
    return OAgentObservation(**canonical_payload, content_hash=digest(canonical_payload))


def test_o_agent_schema_is_versioned_and_does_not_compute_trajectory_viability():
    value = observation()
    assert value.schema_version == "o-agent-v0"
    assert value.facts.local_decision_state == "PERMIT"
    assert value.facts.local_decision_scope == "LOCAL_DECISION_ONLY"
    assert value.facts.trajectory_viability is None
    assert "AUTONOMY_RUN_NOT_LINKED" in value.missing_data


def test_o_agent_canonical_bytes_and_hash_are_stable():
    first = observation()
    second = observation()
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.content_hash == second.content_hash
    assert first.content_hash == digest(first.canonical_payload())


def test_o_agent_rejects_unversioned_extra_fields():
    payload = observation().model_dump(mode="json")
    payload["unexpected"] = True
    try:
        OAgentObservation.model_validate(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("O_AGENT must reject schema drift")
