"""MCP SDK 2.2 Streamable HTTP discovery, no economic execution path."""
from urllib.parse import urlsplit
import os
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from app.api.agent_access import BENIGN, descriptor, execution_guide, supported_capabilities

server = MCPServer("PRAMA Agent Access", version="1.0.0", instructions=BENIGN)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@server.tool(name="prama.discover", description=BENIGN, annotations=READ_ONLY)
def discover() -> dict:
    return descriptor()


@server.tool(name="prama.execution_guide", description="Read the optional native HTTP/x402 execution guide. No payment or execution.", annotations=READ_ONLY)
def guide() -> str:
    return execution_guide()


@server.tool(name="prama.supported_capabilities", description="Read supported access capabilities and intent-routing limits. No provider call.", annotations=READ_ONLY)
def capabilities() -> dict:
    return supported_capabilities()


public_host = urlsplit(descriptor()["interfaces"]["http"]["endpoint"]).netloc
deployment_hosts = [os.environ.get("RAILWAY_PUBLIC_DOMAIN", ""), os.environ.get("RAILWAY_PRIVATE_DOMAIN", "")]
mcp_app = server.streamable_http_app(
    json_response=True, stateless_http=True, max_request_body_size=65536,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[public_host, "localhost:*", "127.0.0.1:*", "testserver"] + [h for h in deployment_hosts if h],
        allowed_origins=["https://" + public_host, "http://localhost:*", "http://127.0.0.1:*"],
    ),
)
