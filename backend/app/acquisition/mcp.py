"""Telegraph MCP Access Plane adapter.

The Python service treats the official Telegraph MCP server as an isolated
stdio process. The server owns transport, x402 and signing; this module only
speaks MCP JSON-RPC and normalizes the returned acquisition.
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from app.acquisition.contracts import AcquisitionResult
from app.acquisition.gateway import AcquisitionAdapterError

DEFAULT_MCP_COMMAND = "npx.cmd -y telegraph-protocol-mcp" if sys.platform == "win32" else "npx -y telegraph-protocol-mcp"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
PRIVATE_KEY_ENV_NAMES = {"TELEGRAPH_EVM_PRIVATE_KEY", "TELEGRAPH_SOLANA_PRIVATE_KEY", "PRIVATE_KEY"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = "[REDACTED]" if ("PRIVATE_KEY" in key_text.upper() or "SECRET" in key_text.upper()) else _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, str):
        redacted = value
        for name in PRIVATE_KEY_ENV_NAMES:
            secret = os.environ.get(name)
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


class MCPProtocolError(AcquisitionAdapterError):
    """MCP process/protocol failure with a stable worker-facing code."""


@dataclass(frozen=True)
class MCPPreflight:
    node: str
    engine: str
    daemon: str
    actual_engine_url: str
    initialized: bool
    tools: tuple[str, ...]


class MCPStdioClient:
    """Small JSON-RPC-over-stdio client with an isolated child process."""

    def __init__(self, command: Sequence[str], *, environment: dict[str, str] | None = None, timeout_seconds: float = 120, protocol_version: str = DEFAULT_PROTOCOL_VERSION, popen_factory: Any = subprocess.Popen) -> None:
        self.command = list(command)
        self.environment = dict(environment or os.environ)
        self.timeout_seconds = timeout_seconds
        self.protocol_version = protocol_version
        self._popen_factory = popen_factory
        self._process: Any = None
        self._next_id = 1
        self._stderr: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    @property
    def stderr_text(self) -> str:
        return "".join(self._stderr)

    def __enter__(self) -> "MCPStdioClient":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = self._popen_factory(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=dict(self.environment))
        except OSError as error:
            raise MCPProtocolError("MCP_PROCESS_START_FAILED") from error
        self._stderr_thread = threading.Thread(target=self._collect_stderr, daemon=True)
        self._stderr_thread.start()

    def _collect_stderr(self) -> None:
        stream = getattr(self._process, "stderr", None)
        if stream is None:
            return
        try:
            for line in stream:
                self._stderr.append(str(_redact(line)))
        except (OSError, ValueError):
            return

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except (OSError, ValueError):
                pass

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise MCPProtocolError("MCP_PROCESS_NOT_STARTED")
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = _redact(params)
        try:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as error:
            raise MCPProtocolError("MCP_PROCESS_WRITE_FAILED") from error
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            line_queue: queue.Queue[str] = queue.Queue(maxsize=1)
            threading.Thread(target=self._readline, args=(process.stdout, line_queue), daemon=True).start()
            try:
                line = line_queue.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty as error:
                raise MCPProtocolError("MCP_REQUEST_TIMEOUT") from error
            if not line:
                code = process.poll()
                error_code = "MCP_PROCESS_EXITED" if code is not None else "MCP_PROTOCOL_EOF"
                raise MCPProtocolError(error_code, raw_payload={"stderr": self.stderr_text[-2048:]})
            try:
                response = json.loads(line)
            except (TypeError, ValueError) as error:
                raise MCPProtocolError("MCP_MALFORMED_RESPONSE") from error
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response.get("error") or {}
                code = error.get("code", "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
                raise MCPProtocolError(f"MCP_RPC_ERROR_{code}", raw_payload=_redact(response))
            result = response.get("result")
            if not isinstance(result, dict):
                raise MCPProtocolError("MCP_INVALID_RESULT", raw_payload=_redact(response))
            return result
        raise MCPProtocolError("MCP_REQUEST_TIMEOUT")

    @staticmethod
    def _readline(stream: Any, target: queue.Queue[str]) -> None:
        try:
            target.put(stream.readline())
        except (OSError, ValueError):
            try:
                target.put("")
            except queue.Full:
                pass

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {"protocolVersion": self.protocol_version, "capabilities": {}, "clientInfo": {"name": "prama-dynamagh", "version": "1.0.0"}})
        process = self._process
        if process is not None and process.stdin is not None:
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            process.stdin.flush()
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise MCPProtocolError("MCP_TOOLS_LIST_INVALID", raw_payload=_redact(result))
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": _redact(arguments)})


def _configured_command() -> list[str]:
    configured = os.environ.get("TELEGRAPH_MCP_COMMAND", "").strip()
    return shlex.split(configured or DEFAULT_MCP_COMMAND, posix=sys.platform != "win32")


def _extract_content(result: dict[str, Any]) -> Any:
    if result.get("isError"):
        raise MCPProtocolError("MCP_TOOL_ERROR", raw_payload=_redact(result))
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    content = result.get("content")
    if not isinstance(content, list):
        raise MCPProtocolError("MCP_TOOL_RESPONSE_INVALID", raw_payload=_redact(result))
    texts = [item.get("text") for item in content if isinstance(item, dict) and item.get("type") == "text"]
    if not texts:
        raise MCPProtocolError("MCP_TOOL_RESPONSE_EMPTY", raw_payload=_redact(result))
    text = "\n".join(str(item) for item in texts)
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {"text": text}


def _decimal_cost(payload: dict[str, Any], budget_usdc: Decimal) -> Decimal:
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    value = payment.get("amount_usdc", payload.get("cost_usdc", payload.get("cost_usd")))
    if value is None:
        raise MCPProtocolError("PAYMENT_COST_UNAVAILABLE", raw_payload=_redact(payload))
    try:
        cost = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise MCPProtocolError("PAYMENT_COST_UNAVAILABLE", raw_payload=_redact(payload)) from error
    if not cost.is_finite() or cost < 0 or cost > budget_usdc or cost.as_tuple().exponent < -6:
        raise MCPProtocolError("SINGLE_ACQUISITION_BUDGET_EXCEEDED", raw_payload=_redact(payload))
    return cost


class TelegraphMCPAdapter:
    """Provider-neutral acquisition through the official Telegraph MCP server."""

    provider = "TELEGRAPH"

    def __init__(self, *, command: Sequence[str], timeout_seconds: int = 120, environment: dict[str, str] | None = None, client_factory: Any = MCPStdioClient) -> None:
        self.command = list(command)
        self.timeout_seconds = timeout_seconds
        self.environment = dict(environment or os.environ)
        self._client_factory = client_factory

    @classmethod
    def from_environment(cls, *, timeout_seconds: int = 120) -> "TelegraphMCPAdapter":
        return cls(command=_configured_command(), timeout_seconds=timeout_seconds)

    def _client(self) -> MCPStdioClient:
        return self._client_factory(self.command, environment=self.environment, timeout_seconds=self.timeout_seconds, protocol_version=os.environ.get("MCP_PROTOCOL_VERSION", DEFAULT_PROTOCOL_VERSION))

    def preflight(self) -> MCPPreflight:
        with self._client() as client:
            client.initialize()
            tools = client.list_tools()
        names = tuple(sorted(str(item.get("name")) for item in tools if item.get("name")))
        expected = {"tg_node_status", "tg_engine_list_subnets", "tg_engine_ask"}
        missing = expected.difference(names)
        if missing:
            raise MCPProtocolError("MCP_EXPECTED_TOOLS_UNAVAILABLE", raw_payload={"missing": sorted(missing)})
        return MCPPreflight(node=os.environ.get("TELEGRAPH_NODE_URL", ""), engine=os.environ.get("TELEGRAPH_ENGINE_URL", ""), daemon=os.environ.get("TELEGRAPH_DAEMON_URL", ""), actual_engine_url=os.environ.get("TELEGRAPH_ENGINE_URL", ""), initialized=True, tools=names)

    def acquire(self, *, query: str, requested_intent: str | None, causal_request_id: str, budget_usdc: Decimal) -> AcquisitionResult:
        arguments: dict[str, Any] = {"query": query}
        with self._client() as client:
            client.initialize()
            tools = {str(item.get("name")): item for item in client.list_tools()}
            if "tg_engine_ask" not in tools:
                raise MCPProtocolError("MCP_TOOL_UNAVAILABLE", raw_payload={"tool": "tg_engine_ask"})
            started = time.monotonic()
            tool_result = client.call_tool("tg_engine_ask", arguments)
            duration_ms = int((time.monotonic() - started) * 1000)
        payload = _extract_content(tool_result)
        if not isinstance(payload, dict):
            payload = {"mcp_response": payload}
        payload = _redact(payload)
        cost = _decimal_cost(payload, budget_usdc)
        miner_id = payload.get("miner_id") or payload.get("minerId")
        signal_hash = payload.get("signal_hash") or payload.get("signalHash")
        intent = payload.get("intent") or requested_intent
        if not miner_id or not signal_hash or not intent:
            raise MCPProtocolError("TELEGRAPH_INVALID_RESPONSE", raw_payload=payload)
        return AcquisitionResult(provider=self.provider, access_mechanism="MCP", miner_id=str(miner_id), miner_name=payload.get("miner_name") or payload.get("minerName"), intent=str(intent), signal_hash=str(signal_hash), cost_usdc=cost, duration_ms=payload.get("duration_ms", duration_ms), reasoning=payload.get("reasoning"), warnings=payload.get("warnings") or [], raw_payload=payload, http_status=payload.get("http_status"))
