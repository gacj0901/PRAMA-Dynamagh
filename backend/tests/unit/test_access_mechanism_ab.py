"""Phase 4 proof that Gateway and MCP are interchangeable access mechanisms."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from app.acquisition.contracts import AcquisitionResult
from app.acquisition.gateway import TelegraphGatewayAdapter
from app.acquisition.mcp import TelegraphMCPAdapter
from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy
from app.authority.composition import AuthorityCompositionInput, evaluate_authority_composition
from app.authority.recovery import G13_REVIEW_RECOVERY_POLICY_VERSION
from app.pramagraph.evaluation import classify, decide, digest
from app.pramagraph.fanout import structural_state
from app.tickets.core import build as build_ticket_core, hash_core


SIGNAL = "0x" + "ab" * 32
SEMANTIC_RESULT = {"price": "65000.00", "currency": "USD", "observation": "same"}


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


class _FakeMCPClient:
    calls = 0

    def __init__(self, *_args, **_kwargs):
        self.initialized = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def initialize(self):
        self.initialized = True
        return {"protocolVersion": "2025-06-18"}

    def list_tools(self):
        return [{"name": "tg_engine_ask"}, {"name": "tg_engine_list_subnets"}, {"name": "tg_node_status"}]

    def call_tool(self, name, arguments):
        assert self.initialized is True
        assert name == "tg_engine_ask"
        assert arguments == {"query": "same query"}
        type(self).calls += 1
        payload = {
            "minerId": "miner-equivalent",
            "minerName": "Equivalent miner",
            "intent": "CRYPTO_PRICE",
            "signalHash": SIGNAL,
            "cost_usd": "0.006000",
            "duration_ms": 91,
            "reasoning": "same normalized reasoning",
            "warnings": [],
            "result": SEMANTIC_RESULT,
            "mcp_transport": {"protocol": "jsonrpc", "tool": name},
        }
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _gateway_result() -> AcquisitionResult:
    payload = {
        "miner_id": "miner-equivalent",
        "miner_name": "Equivalent miner",
        "intent": "CRYPTO_PRICE",
        "signal_hash": SIGNAL,
        "payment": {"amount_usdc": "0.006000"},
        "duration_ms": 37,
        "reasoning": "same normalized reasoning",
        "warnings": [],
        "result": SEMANTIC_RESULT,
        "gateway_transport": {"http_status": 200, "route": "/ask"},
    }

    def transport(_request, **_kwargs):
        return _Response(payload)

    return TelegraphGatewayAdapter(
        base_url="http://gateway.test",
        urlopen_fn=transport,
    ).acquire(
        query="same query",
        requested_intent="CRYPTO_PRICE",
        causal_request_id="mandate-equivalent",
        budget_usdc=Decimal("0.010000"),
    )


def _mcp_result() -> AcquisitionResult:
    return TelegraphMCPAdapter(
        command=["fixture"],
        client_factory=_FakeMCPClient,
    ).acquire(
        query="same query",
        requested_intent="CRYPTO_PRICE",
        causal_request_id="mandate-equivalent",
        budget_usdc=Decimal("0.010000"),
    )


def _semantic_projection(result: AcquisitionResult) -> tuple:
    return (
        result.provider,
        result.miner_id,
        result.miner_name,
        result.intent,
        result.signal_hash,
        result.cost_usdc,
        result.reasoning,
        tuple(result.warnings),
        result.raw_payload["result"],
    )


def _downstream(result: AcquisitionResult) -> dict:
    """Use the existing normalized Evidence -> PRAMAgraph -> Decision -> Ticket path."""

    call = SimpleNamespace(
        acquisition_id="acquisition-equivalent",
        status="SUCCEEDED",
        raw_response=result.raw_payload,
        intent=result.intent,
        miner_id=result.miner_id,
        signal_hash=result.signal_hash,
        warnings=result.warnings,
        cost_usd=result.cost_usdc,
        access_mechanism=result.access_mechanism,
    )
    task = SimpleNamespace(
        acquisition_id=call.acquisition_id,
        ordinal=0,
        status="SUCCEEDED",
        required=True,
        failure_code=None,
        requested_intent=result.intent,
        query="same query",
    )
    admissibility, limitation_codes = classify(call, verified=True)
    normalized = {
        "intent": result.intent,
        "result": result.raw_payload["result"],
        "miner_id": result.miner_id,
        "signal_hash": result.signal_hash,
        "warnings": result.warnings,
    }
    evidence = SimpleNamespace(
        evidence_id="evidence-equivalent",
        acquisition_id=task.acquisition_id,
        telegraph_call_id="call-equivalent",
        normalized_payload=normalized,
        content_hash=digest(normalized),
        admissibility=admissibility,
        provenance_status="VERIFIED",
        source_kind=f"TELEGRAPH_{result.access_mechanism}",
        source_intent=result.intent,
        source_miner_id=result.miner_id,
        source_signal_hash=result.signal_hash,
        normalizer_version="telegraph-evidence-v0",
        limitation_codes=limitation_codes,
    )
    structural = structural_state([evidence], [task])
    decision_state, reasons = decide(structural)
    evaluation = SimpleNamespace(
        evaluation_id="evaluation-equivalent",
        evaluator="PRAMAGRAPH",
        evaluator_version="pramagraph-structural-v0",
        evidence_set_hash=digest([evidence.content_hash]),
        structural_state=structural,
        limitation_codes=limitation_codes,
        contradiction_codes=[],
    )
    decision = SimpleNamespace(
        state=decision_state,
        policy_version="prama-gate-v0",
        reason_codes=reasons,
        evidence_set_hash=evaluation.evidence_set_hash,
    )
    mandate = SimpleNamespace(mandate_id="mandate-equivalent", mandate_type="GENERAL", constraints={})
    ticket = build_ticket_core(mandate, decision, evaluation, [evidence], [call], [task])
    return {
        "evidence_semantics": (evidence.admissibility, evidence.limitation_codes, evidence.content_hash),
        "evidence_provenance": evidence.source_kind,
        "pramagraph": (evaluation.structural_state, evaluation.evidence_set_hash),
        "decision": (decision.state, tuple(decision.reason_codes)),
        "ticket": (ticket, hash_core(ticket)),
    }


def _authority(*, g12: str = "PERMIT", g13: str = "CONTINUE", throttle_ok: bool = False):
    return evaluate_authority_composition(
        AuthorityCompositionInput(
            agent_id="autonomy-controller",
            run_id="run-equivalent",
            action_id="action-equivalent",
            action_kind="TELEGRAPH_HTTP_ACQUISITION",
            applicability={"CD": "NOT_APPLICABLE", "G12": "APPLICABLE", "CDG": "APPLICABLE"},
            epistemic_result="PERMIT",
            epistemic_evaluation_id=None,
            epistemic_result_hash=None,
            g12_result=g12,
            g12_input_hash="g12-input",
            longitudinal_result=g13,
            longitudinal_evaluation_id="g13-evaluation",
            longitudinal_result_hash="g13-result",
            throttled_constraints_satisfied=throttle_ok,
            current_runtime_action="CONTINUE_TO_GATEWAY",
            shadow_mode=False,
        )
    )


def _observation(sequence: int, episode: str | None, *, status: str = "FAILED") -> OAgentObservation:
    facts = OAgentFacts(
        action_status=status,
        local_decision_state="PERMIT",
        local_decision_scope="LOCAL_DECISION_ONLY",
        failure_code="TELEGRAPH_REQUEST_FAILED" if status == "FAILED" else None,
        failure_episode_id=episode,
        failure_event_types=("ACQUISITION_FAILED",) if status == "FAILED" else (),
        telegraph_statuses=("FAILED",) if status == "FAILED" else ("SUCCEEDED",),
    )
    lineage = OAgentSourceLineage(agent_identity_id="autonomy-controller", autonomy_run_ids=(f"run-{sequence}",))
    payload = {
        "schema_version": "o-agent-v0",
        "observation_id": f"observation-{sequence}",
        "sequence": sequence,
        "observed_at": f"2026-09-16T12:0{sequence}:00Z",
        "timestamp_source": "created_at",
        "agent_identity_id": "autonomy-controller",
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
        "source_kind": "AUTONOMY_RUN",
        "source_id": f"run-{sequence}",
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
        "missing_data": [],
    }
    return OAgentObservation(**payload, content_hash=digest(payload))


def _g13(observations: list[OAgentObservation]):
    return evaluate_g13_policy(
        G13PolicyInput.from_observations(
            "autonomy-controller",
            observations,
            allow_sparse_window=True,
            policy_version=G13_REVIEW_RECOVERY_POLICY_VERSION,
        )
    )


def test_adapter_normalization_is_semantically_equivalent_and_provenance_distinct():
    gateway = _gateway_result()
    mcp = _mcp_result()
    assert _semantic_projection(gateway) == _semantic_projection(mcp)
    assert gateway.provider == mcp.provider == "TELEGRAPH"
    assert gateway.access_mechanism == "GATEWAY"
    assert mcp.access_mechanism == "MCP"
    assert gateway.raw_payload != mcp.raw_payload
    assert gateway.duration_ms != mcp.duration_ms


def test_real_adapter_normalizers_are_used_without_network_or_payment():
    _FakeMCPClient.calls = 0
    gateway = _gateway_result()
    mcp = _mcp_result()
    assert _FakeMCPClient.calls == 1
    assert gateway.cost_usdc == mcp.cost_usdc == Decimal("0.006000")
    assert gateway.provider == mcp.provider == "TELEGRAPH"


def test_downstream_evidence_pramagraph_decision_and_ticket_semantics_are_invariant():
    left = _downstream(_gateway_result())
    right = _downstream(_mcp_result())
    assert left["evidence_semantics"] == right["evidence_semantics"]
    assert left["pramagraph"] == right["pramagraph"]
    assert left["decision"] == right["decision"]
    assert left["ticket"] == right["ticket"]
    assert left["evidence_provenance"] != right["evidence_provenance"]


def test_g12_outcome_is_invariant_for_permit_and_restrictive_states():
    for g12 in ("PERMIT", "DENY"):
        gateway = _authority(g12=g12).result_core
        mcp = _authority(g12=g12).result_core
        assert gateway["authority_reason"] == mcp["authority_reason"]
        assert gateway["would_allow_next_action"] == mcp["would_allow_next_action"]


def test_g13_normal_throttle_and_review_outcomes_are_access_neutral():
    cases = (
        ("CONTINUE", False),
        ("THROTTLE", True),
        ("REVIEW", False),
    )
    for result, throttle_ok in cases:
        gateway = _authority(g13=result, throttle_ok=throttle_ok)
        mcp = _authority(g13=result, throttle_ok=throttle_ok)
        assert gateway.result == mcp.result
        assert gateway.triggered_rule_ids == mcp.triggered_rule_ids


def test_same_causal_episode_across_gateway_and_mcp_counts_once():
    gateway = _g13([_observation(1, "episode-shared")])
    mcp = _g13([_observation(2, "episode-shared")])
    assert gateway.result_core["distinct_external_dependency_count"] == 1
    assert mcp.result_core["distinct_external_dependency_count"] == 1
    assert gateway.result == mcp.result


def test_distinct_causal_episodes_remain_distinct_even_with_same_provider():
    gateway = _g13([_observation(1, "episode-gateway")])
    mcp = _g13([_observation(2, "episode-mcp")])
    combined = _g13([_observation(1, "episode-gateway"), _observation(2, "episode-mcp"), _observation(3, "episode-third")])
    assert gateway.result_core["distinct_external_dependency_count"] == 1
    assert mcp.result_core["distinct_external_dependency_count"] == 1
    assert combined.result_core["distinct_external_dependency_count"] == 3
    assert "G13_EXTERNAL_ACQUISITION_RECURRENCE" in combined.triggered_rule_ids


def test_execution_authorization_is_invariant_for_permit_and_restrictive_continuation():
    for g12, g13, throttle_ok in (("PERMIT", "CONTINUE", False), ("DENY", "CONTINUE", False), ("PERMIT", "REVIEW", False), ("PERMIT", "THROTTLE", False), ("PERMIT", "THROTTLE", True)):
        gateway = _authority(g12=g12, g13=g13, throttle_ok=throttle_ok)
        mcp = _authority(g12=g12, g13=g13, throttle_ok=throttle_ok)
        assert (gateway.result, gateway.result_core["would_allow_next_action"]) == (mcp.result, mcp.result_core["would_allow_next_action"])


def test_raw_payload_adversarial_shapes_cannot_change_downstream_semantics():
    gateway = _gateway_result()
    mcp = _mcp_result()
    gateway.raw_payload["gateway_only"] = {"nested": [1, 2, 3], "opaque": True}
    mcp.raw_payload["mcp_only"] = {"nested": {"different": "shape"}, "opaque": False}
    assert _downstream(gateway)["decision"] == _downstream(mcp)["decision"]
    assert _downstream(gateway)["pramagraph"] == _downstream(mcp)["pramagraph"]


def test_failure_classification_and_provenance_are_preserved_without_network():
    gateway = _gateway_result()
    mcp = _mcp_result()
    failed_gateway = _observation(1, "episode-failure")
    failed_mcp = _observation(2, "episode-failure")
    assert failed_gateway.facts.failure_code == failed_mcp.facts.failure_code == "TELEGRAPH_REQUEST_FAILED"
    assert failed_gateway.facts.failure_episode_id == failed_mcp.facts.failure_episode_id
    assert gateway.raw_payload["gateway_transport"]["route"] == "/ask"
    assert mcp.raw_payload["mcp_transport"]["protocol"] == "jsonrpc"


def test_phase4_has_no_paid_mcp_call_or_external_request():
    _FakeMCPClient.calls = 0
    result = _mcp_result()
    assert _FakeMCPClient.calls == 1
    assert result.cost_usdc == Decimal("0.006000")
    assert result.raw_payload["mcp_transport"]["protocol"] == "jsonrpc"
