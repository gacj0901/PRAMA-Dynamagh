from decimal import Decimal

from app.acquisition.contracts import AcquisitionRequest, AcquisitionResult, ResourceAdapter, X402_PAYMENT_RAIL
from app.acquisition.gateway import TelegraphGatewayAdapter
from app.acquisition.mcp import TelegraphMCPAdapter


def test_acquisition_request_is_provider_neutral():
    request = AcquisitionRequest(
        query="current BTC price",
        requested_intent="CRYPTO_PRICE",
        causal_request_id="mandate-1",
        budget_usdc=Decimal("0.010000"),
    )
    assert request.query == "current BTC price"
    assert request.budget_usdc == Decimal("0.010000")


def test_telegraph_rails_expose_access_and_payment_provenance():
    assert isinstance(TelegraphGatewayAdapter, type)
    assert TelegraphGatewayAdapter.provider == "TELEGRAPH"
    assert TelegraphGatewayAdapter.access_mechanism == "GATEWAY"
    assert TelegraphGatewayAdapter.payment_rail == X402_PAYMENT_RAIL
    assert TelegraphMCPAdapter.provider == "TELEGRAPH"
    assert TelegraphMCPAdapter.access_mechanism == "MCP"
    assert TelegraphMCPAdapter.payment_rail == X402_PAYMENT_RAIL


def test_normalized_result_keeps_payment_rail_outside_authority():
    result = AcquisitionResult(
        provider="TELEGRAPH",
        access_mechanism="GATEWAY",
        payment_rail=X402_PAYMENT_RAIL,
        miner_id="miner-1",
        miner_name="Miner",
        intent="CRYPTO_PRICE",
        signal_hash="0xsignal",
        cost_usdc=Decimal("0.001000"),
        duration_ms=1,
        reasoning=None,
    )
    assert result.payment_rail == "X402"
    assert not hasattr(result, "authority")
