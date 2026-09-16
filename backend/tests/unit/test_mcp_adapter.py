from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.acquisition.mcp import MCPProtocolError, MCPStdioClient, TelegraphMCPAdapter
from app.acquisition.provider import configured_acquisition_adapter
from app.acquisition.gateway import TelegraphGatewayAdapter


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"


def adapter(monkeypatch, mode: str = "normal") -> TelegraphMCPAdapter:
    monkeypatch.setenv("MCP_FIXTURE_MODE", mode)
    return TelegraphMCPAdapter(command=[sys.executable, str(FIXTURE)], timeout_seconds=1)


def test_mcp_lifecycle_initialize_tools_and_normalize(monkeypatch):
    result = adapter(monkeypatch).acquire(query="btc price", requested_intent="CRYPTO_PRICE", causal_request_id="cause-1", budget_usdc=Decimal("0.01"))
    assert result.provider == "TELEGRAPH"
    assert result.access_mechanism == "MCP"
    assert result.miner_id == "177"
    assert result.signal_hash == "0xsignal"
    assert result.cost_usdc == Decimal("0.010000")
    assert result.raw_payload["echo_query"] == "btc price"


def test_mcp_preflight_is_non_paying_and_lists_expected_tools(monkeypatch):
    status = adapter(monkeypatch).preflight()
    assert status.initialized is True
    assert {"tg_node_status", "tg_engine_list_subnets", "tg_engine_ask"}.issubset(status.tools)


def test_mcp_tool_unavailable_fails_closed(monkeypatch):
    with pytest.raises(MCPProtocolError, match="MCP_TOOL_UNAVAILABLE"):
        adapter(monkeypatch, "missing_tool").acquire(query="q", requested_intent="CRYPTO_PRICE", causal_request_id="c", budget_usdc=Decimal("0.01"))


def test_mcp_malformed_response_fails_closed(monkeypatch):
    with pytest.raises(MCPProtocolError, match="MCP_MALFORMED_RESPONSE"):
        adapter(monkeypatch, "malformed").preflight()


def test_mcp_process_timeout_fails_closed(monkeypatch):
    with pytest.raises(MCPProtocolError, match="MCP_REQUEST_TIMEOUT"):
        adapter(monkeypatch, "timeout").preflight()


def test_mcp_process_start_failure_is_typed(monkeypatch):
    with pytest.raises(MCPProtocolError, match="MCP_PROCESS_START_FAILED"):
        TelegraphMCPAdapter(command=["definitely-not-an-executable"], timeout_seconds=1).preflight()


def test_private_key_is_not_in_result_or_stderr(monkeypatch):
    secret = "0xsuper-secret-key"
    monkeypatch.setenv("TELEGRAPH_EVM_PRIVATE_KEY", secret)
    result = adapter(monkeypatch, "stderr_secret").acquire(query="q", requested_intent="CRYPTO_PRICE", causal_request_id="c", budget_usdc=Decimal("0.01"))
    assert secret not in repr(result)
    assert secret not in os.environ.get("TELEGRAPH_MCP_COMMAND", "")


def test_mcp_stderr_is_separate_and_redacted(monkeypatch):
    secret = "0xstderr-secret"
    monkeypatch.setenv("TELEGRAPH_EVM_PRIVATE_KEY", secret)
    monkeypatch.setenv("MCP_FIXTURE_MODE", "stderr_secret")
    client = MCPStdioClient([sys.executable, str(FIXTURE)], timeout_seconds=1)
    with client:
        client.initialize()
    assert secret not in client.stderr_text
    assert "[REDACTED]" in client.stderr_text


def test_gateway_remains_default_and_mcp_has_no_fallback(monkeypatch):
    monkeypatch.delenv("ACQUISITION_PROVIDER", raising=False)
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.test")
    assert isinstance(configured_acquisition_adapter(timeout_seconds=1), TelegraphGatewayAdapter)
    monkeypatch.setenv("ACQUISITION_PROVIDER", "MCP")
    monkeypatch.setenv("TELEGRAPH_MCP_COMMAND", f'"{sys.executable}" "{FIXTURE}"')
    assert isinstance(configured_acquisition_adapter(timeout_seconds=1), TelegraphMCPAdapter)
    monkeypatch.setenv("ACQUISITION_PROVIDER", "UNKNOWN")
    with pytest.raises(ValueError, match="Unsupported ACQUISITION_PROVIDER"):
        configured_acquisition_adapter(timeout_seconds=1)
