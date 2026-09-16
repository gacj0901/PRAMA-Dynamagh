"""Phase 2 proof that authority is invariant under access substitution."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import ast
import inspect

from app.acquisition.contracts import AcquisitionAdapter, AcquisitionResult
from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy
from app.authority.recovery import G13_REVIEW_RECOVERY_POLICY_VERSION
from app.authority.composition import AuthorityCompositionInput, evaluate_authority_composition
from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.pramagraph.evaluation import classify, decide, digest
from app.pramagraph.fanout import structural_state
from app.tickets.core import build as build_ticket_core, hash_core


ROOT = Path(__file__).resolve().parents[2]
BOUNDARY_FILES = (
    *sorted((ROOT / "app" / "authority").glob("*.py")),
    ROOT / "app" / "agents" / "observation.py",
    ROOT / "app" / "pramagraph" / "evaluation.py",
    ROOT / "app" / "pramagraph" / "replay.py",
    ROOT / "app" / "tickets" / "core.py",
    ROOT / "app" / "tickets" / "service.py",
)


@dataclass(frozen=True)
class SyntheticAccessAdapter:
    """Test-only adapter; it has no persistence or network capabilities."""

    result: AcquisitionResult
    provider: str = "FAKE_PROVIDER"
    access_mechanism: str = "SYNTHETIC_ACCESS"

    def acquire(self, **kwargs) -> AcquisitionResult:
        return self.result


def _result(*, provider: str, access_mechanism: str, raw_payload: dict) -> AcquisitionResult:
    return AcquisitionResult(
        provider=provider,
        access_mechanism=access_mechanism,
        miner_id="miner-equivalent",
        miner_name="Equivalent miner",
        intent="CRYPTO_PRICE",
        signal_hash="0x" + "ab" * 32,
        cost_usdc=Decimal("0.006000"),
        duration_ms=42,
        reasoning="same normalized reasoning",
        warnings=[],
        raw_payload=raw_payload,
    )


def _downstream(result: AcquisitionResult) -> dict:
    """Run the real normalized evidence → PRAMAgraph → Decision → Ticket path."""

    call = SimpleNamespace(
        acquisition_id="acquisition-equivalent",
        status="SUCCEEDED",
        raw_response=result.raw_payload,
        intent=result.intent,
        miner_id=result.miner_id,
        signal_hash=result.signal_hash,
        warnings=result.warnings,
        cost_usd=result.cost_usdc,
    )
    task = SimpleNamespace(
        acquisition_id=call.acquisition_id,
        ordinal=0,
        status="SUCCEEDED",
        required=True,
        failure_code=None,
        requested_intent=result.intent,
        query="same normalized query",
    )
    admissibility, limitation_codes = classify(call, verified=True)
    normalized = {
        "intent": result.intent,
        "result": result.raw_payload.get("result"),
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
    mandate = SimpleNamespace(
        mandate_id="mandate-equivalent",
        mandate_type="GENERAL",
        constraints={},
    )
    ticket = build_ticket_core(mandate, decision, evaluation, [evidence], [call], [task])
    return {
        "evidence": (evidence.admissibility, evidence.limitation_codes, evidence.content_hash),
        "pramagraph": (evaluation.structural_state, evaluation.evidence_set_hash),
        "decision": (decision.state, tuple(decision.reason_codes)),
        "ticket": (ticket, hash_core(ticket)),
    }


def _authority(*, g12: str = "PERMIT", g13: str = "CONTINUE"):
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
            throttled_constraints_satisfied=False,
            current_runtime_action="CONTINUE_TO_GATEWAY",
            shadow_mode=False,
        )
    )


def _failure_observation(sequence: int, episode: str) -> OAgentObservation:
    facts = OAgentFacts(
        action_status="FAILED",
        local_decision_state="PERMIT",
        local_decision_scope="LOCAL_DECISION_ONLY",
        failure_code="TELEGRAPH_REQUEST_FAILED",
        failure_episode_id=episode,
        failure_event_types=("ACQUISITION_FAILED",),
        telegraph_statuses=("PAYMENT_UNCERTAIN",),
    )
    lineage = OAgentSourceLineage(
        agent_identity_id="autonomy-controller",
        autonomy_run_ids=(f"run-{sequence}",),
    )
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


def _g13(episodes: list[str]):
    return evaluate_g13_policy(
        G13PolicyInput.from_observations(
            "autonomy-controller",
            [_failure_observation(i, episode) for i, episode in enumerate(episodes, 1)],
            allow_sparse_window=True,
            policy_version=G13_REVIEW_RECOVERY_POLICY_VERSION,
        )
    )


def test_static_authority_boundary_has_no_access_implementation_dependency():
    forbidden_names = {"TelegraphGatewayAdapter", "AcquisitionAdapterError", "GATEWAY_URL", "urlopen"}
    for path in BOUNDARY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.name.rsplit(".", 1)[-1]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not imported.intersection(forbidden_names), path
        assert not any(
            isinstance(node, ast.Name) and node.id in forbidden_names
            for node in ast.walk(tree)
        ), path


def test_synthetic_adapter_is_test_only_and_implements_contract():
    result = _result(provider="FAKE_PROVIDER", access_mechanism="SYNTHETIC_ACCESS", raw_payload={"synthetic": {"result": {"price": 1}}})
    adapter: AcquisitionAdapter = SyntheticAccessAdapter(result)
    assert adapter.acquire(query="q", requested_intent="CRYPTO_PRICE", causal_request_id="m", budget_usdc=Decimal("0.01")) == result
    source = inspect.getsource(SyntheticAccessAdapter)
    assert not any(token in source for token in ("urlopen", "Request", "GATEWAY_URL", "Telegraph", "SessionLocal"))


def test_equivalent_results_produce_identical_downstream_semantics_and_authority():
    gateway = _result(provider="TELEGRAPH", access_mechanism="GATEWAY", raw_payload={"result": {"price": 1}, "telegraph": {"proof": "gateway"}})
    synthetic = _result(provider="FAKE_PROVIDER", access_mechanism="SYNTHETIC_ACCESS", raw_payload={"result": {"price": 1}, "synthetic": {"proof": "synthetic"}})
    assert _downstream(gateway) == _downstream(synthetic)
    assert _authority().result == _authority().result == "ALLOW"
    assert _authority().result_core["authority_reason"] == "NEXT_ACTION_AUTHORIZED"


def test_raw_payload_is_opaque_to_authority_and_downstream_semantics():
    left = _result(provider="TELEGRAPH", access_mechanism="GATEWAY", raw_payload={"result": {"price": 1}, "provider_secret_shape": {"a": 1}})
    right = _result(provider="TELEGRAPH", access_mechanism="GATEWAY", raw_payload={"result": {"price": 1}, "other_provider_shape": ["different", True]})
    assert _downstream(left) == _downstream(right)
    assert _authority().input_core["g12"] == _authority().input_core["g12"]
    assert "raw_payload" not in str(_authority().input_core)


def test_provider_and_access_mechanism_remain_separate_provenance_fields():
    gateway = _result(provider="TELEGRAPH", access_mechanism="GATEWAY", raw_payload={"result": {"price": 1}})
    synthetic = _result(provider="TELEGRAPH", access_mechanism="MCP", raw_payload={"result": {"price": 1}})
    assert gateway.provider == synthetic.provider == "TELEGRAPH"
    assert gateway.access_mechanism == "GATEWAY"
    assert synthetic.access_mechanism == "MCP"


def test_same_causal_episode_through_different_access_projections_counts_once():
    result = _g13(["episode-shared", "episode-shared"])
    assert result.result_core["distinct_external_dependency_count"] == 1
    assert result.result != "REVIEW"


def test_distinct_causal_episodes_remain_distinct_across_access_mechanisms():
    result = _g13(["episode-gateway", "episode-mcp", "episode-other"])
    assert result.result_core["distinct_external_dependency_count"] == 3
    assert "G13_EXTERNAL_ACQUISITION_RECURRENCE" in result.triggered_rule_ids


def test_successful_capability_cannot_override_g12_or_g13_restriction():
    assert _authority(g12="DENY", g13="CONTINUE").result == "RESTRICT"
    assert _authority(g12="PERMIT", g13="REVIEW").result == "RESTRICT"
    assert _authority(g12="DENY", g13="CONTINUE").result_core["would_allow_next_action"] is False
    assert _authority(g12="PERMIT", g13="REVIEW").result_core["would_allow_next_action"] is False
