"""Tiny stdio MCP fixture used by adapter tests; never used in production."""

import json
import os
import sys
import time

mode = os.environ.get("MCP_FIXTURE_MODE", "normal")
if mode == "stderr_secret":
    print(f"fixture key={os.environ.get('TELEGRAPH_EVM_PRIVATE_KEY', '')}", file=sys.stderr, flush=True)

for raw in sys.stdin:
    try:
        message = json.loads(raw)
    except ValueError:
        print("not-json", flush=True)
        continue
    request_id = message.get("id")
    method = message.get("method")
    if method == "notifications/initialized":
        continue
    if mode == "malformed":
        print("not-json", flush=True)
        continue
    if mode == "timeout":
        time.sleep(5)
        continue
    if method == "initialize":
        result = {"protocolVersion": message.get("params", {}).get("protocolVersion"), "capabilities": {}, "serverInfo": {"name": "fixture"}}
    elif method == "tools/list":
        names = ["tg_node_status", "tg_engine_list_subnets", "tg_engine_ask"]
        if mode == "missing_tool":
            names = ["tg_node_status"]
        result = {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in names]}
    elif method == "tools/call":
        arguments = message.get("params", {}).get("arguments", {})
        result = {"content": [{"type": "text", "text": json.dumps({"miner_id": "177", "miner_name": "fixture-miner", "intent": "CRYPTO_PRICE", "signal_hash": "0xsignal", "cost_usdc": "0.010000", "duration_ms": 12, "reasoning": "fixture", "warnings": [], "echo_query": arguments.get("query")})}]}
    else:
        result = {"error": {"code": -32601, "message": "method not found"}}
    response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    print(json.dumps(response), flush=True)
