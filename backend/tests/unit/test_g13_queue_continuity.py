from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy


def _projection(action_status: str, *, failure_code: str | None = None) -> dict:
    return {
        "observation_id": f"projection-{action_status.lower()}",
        "source_lineage": {"autonomy_run_ids": ["run-race"]},
        "facts": {
            "mandate_status": "TICKETED",
            "acquisition_statuses": ["SUCCEEDED"],
            "telegraph_statuses": ["SUCCEEDED"],
            "failure_code": failure_code,
            "evidence_complete": True,
            "evaluation_complete": True,
            "decision_complete": True,
            "ticket_complete": True,
        },
        "missing_data": [],
        "action_status": action_status,
    }


def test_completed_acquisition_cancels_orphaned_dispatch_failure_for_g13():
    value = G13PolicyInput(
        agent_id="autonomy-controller",
        trajectory_lineage_id="trajectory-race",
        observation_refs=("failure", "success"),
        ordered_observations=(
            _projection("AUTONOMY_RUN_FAILED", failure_code="AUTONOMY_ORPHANED_MANDATE"),
            _projection("ACQUISITION_COMPLETED"),
        ),
        window_definition={},
        o_agent_contract_version="o-agent-v0",
    )

    result = evaluate_g13_policy(value)

    assert result.result == "CONTINUE"
    assert result.result_core["distinct_failure_count"] == 0
    assert "G13_REPEATED_EXECUTION_FAILURE" not in result.triggered_rule_ids


def test_orphaned_dispatch_bookkeeping_does_not_block_later_slots():
    value = G13PolicyInput(
        agent_id="autonomy-controller",
        trajectory_lineage_id="trajectory-race-only",
        observation_refs=("orphaned-1", "orphaned-2"),
        ordered_observations=(
            {
                **_projection("AUTONOMY_RUN_FAILED", failure_code="AUTONOMY_ORPHANED_MANDATE"),
                "facts": {
                    **_projection("AUTONOMY_RUN_FAILED", failure_code="AUTONOMY_ORPHANED_MANDATE")["facts"],
                    "mandate_status": "TICKETED",
                    "acquisition_statuses": ["SUCCEEDED"],
                    "telegraph_statuses": ["SUCCEEDED", "PAYMENT_UNCERTAIN"],
                    "evidence_complete": True,
                    "evaluation_complete": True,
                    "decision_complete": True,
                    "ticket_complete": True,
                },
            },
            {
                **_projection("AUTONOMY_RUN_FAILED", failure_code="AUTONOMY_ORPHANED_MANDATE"),
                "observation_id": "projection-orphaned-2",
                "facts": {
                    **_projection("AUTONOMY_RUN_FAILED", failure_code="AUTONOMY_ORPHANED_MANDATE")["facts"],
                    "mandate_status": "TICKETED",
                    "acquisition_statuses": ["SUCCEEDED"],
                    "telegraph_statuses": ["SUCCEEDED", "PAYMENT_UNCERTAIN"],
                    "evidence_complete": True,
                    "evaluation_complete": True,
                    "decision_complete": True,
                    "ticket_complete": True,
                },
            },
        ),
        window_definition={},
        o_agent_contract_version="o-agent-v0",
    )

    result = evaluate_g13_policy(value)

    assert result.result == "CONTINUE"
    assert result.result_core["distinct_block_count"] == 0
    assert result.result_core["distinct_failure_count"] == 0
