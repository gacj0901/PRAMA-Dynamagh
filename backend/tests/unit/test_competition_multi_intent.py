from decimal import Decimal


def test_competition_call_ceiling_is_bounded_and_configurable(monkeypatch):
    from app.competition import competition_max_calls_per_workflow, competition_budget_profile

    assert competition_max_calls_per_workflow() == 5
    monkeypatch.setenv("COMPETITION_MAX_CALLS_PER_WORKFLOW", "3")
    assert competition_max_calls_per_workflow() == 3
    monkeypatch.setenv("COMPETITION_MAX_CALLS_PER_WORKFLOW", "99")
    assert competition_max_calls_per_workflow() == 5
    profile = competition_budget_profile()
    assert profile["max_real_calls_per_workflow"] == 5
    assert profile["multi_intent_enabled"] is True


def test_authorized_g12_limits_are_bounded(monkeypatch):
    from app.public_safety import (
        MAX_DAILY_SPEND_CAP_USDC,
        MAX_SINGLE_ACQUISITION_USDC,
        MAX_WORKFLOW_SPEND_USDC,
        global_daily_spend_cap_usdc,
        m2m_max_workflow_usdc,
        public_max_mandate_usdc,
    )

    monkeypatch.delenv("PUBLIC_MAX_MANDATE_USDC", raising=False)
    monkeypatch.delenv("M2M_MAX_WORKFLOW_USDC", raising=False)
    monkeypatch.delenv("GLOBAL_DAILY_SPEND_CAP_USDC", raising=False)
    monkeypatch.delenv("PUBLIC_DAILY_SPEND_CAP_USDC", raising=False)
    assert public_max_mandate_usdc() == MAX_WORKFLOW_SPEND_USDC == Decimal("0.500000")
    assert m2m_max_workflow_usdc() == MAX_WORKFLOW_SPEND_USDC
    assert global_daily_spend_cap_usdc() == MAX_DAILY_SPEND_CAP_USDC == Decimal("20.000000")
    assert MAX_SINGLE_ACQUISITION_USDC == Decimal("0.050000")
    monkeypatch.setenv("PUBLIC_MAX_MANDATE_USDC", "1.00")
    monkeypatch.setenv("M2M_MAX_WORKFLOW_USDC", "1.00")
    monkeypatch.setenv("GLOBAL_DAILY_SPEND_CAP_USDC", "100.00")
    assert public_max_mandate_usdc() == MAX_WORKFLOW_SPEND_USDC
    assert m2m_max_workflow_usdc() == MAX_WORKFLOW_SPEND_USDC
    assert global_daily_spend_cap_usdc() == MAX_DAILY_SPEND_CAP_USDC


def test_single_call_budget_remains_g12_bounded(monkeypatch):
    from app.competition import competition_budget_profile

    monkeypatch.setenv("COMPETITION_MAX_WORKFLOW_USDC", "0.050000")
    profile = competition_budget_profile()
    assert profile["effective_max_usdc_per_workflow"] == "0.050000"
    assert profile["g12_hard_cap_applied"] is False


def test_multiple_acquisition_models_are_explicit_and_opaque():
    from app.api.mandates import AcquisitionInput
    from app.api.m2m import M2MAcquisitionInput

    public = AcquisitionInput(query="Find the current BTC/USD price", requested_intent="CRYPTO_PRICE")
    m2m = M2MAcquisitionInput(query="Find current network gas conditions", requested_intent="GAS_PRICE")
    assert public.query and public.requested_intent == "CRYPTO_PRICE"
    assert m2m.query and m2m.requested_intent == "GAS_PRICE"
